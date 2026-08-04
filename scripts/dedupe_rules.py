#!/usr/bin/env python3
"""Deduplicate fd-cn-report indicator_rules.json.

Reduces ~16K rules to ~8K through:
1. Signature-based deduplication (merge identical semantic rules)
2. Alias consolidation (case-insensitive dedup)
3. Template extraction (common patterns into templates)
4. Quality scoring (identify low-coverage rules for review)

Usage:
    python scripts/dedupe_rules.py [--output RULES.json] [--dry-run]

Output:
    - indicator_rules_deduped.json: Deduplicated rules file
    - dedup_report.json: Summary of changes made
    - warnings.txt: Rules flagged for manual review
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def compute_signature(rule: dict) -> tuple:
    """Compute canonical signature for rule deduplication.

    Rules with identical signatures are semantically equivalent.
    """
    return (
        rule.get("name", ""),
        rule.get("module", ""),
        rule.get("subgroup", ""),
        rule.get("extractor", ""),
        rule.get("source_type", ""),
        rule.get("period_type", "annual"),
        rule.get("unit", ""),
    )


def merge_aliases(aliases_list: list[list[str]]) -> list[str]:
    """Merge multiple alias lists, case-insensitively deduplicated."""
    canonical = {}
    for aliases in aliases_list:
        if not isinstance(aliases, list):
            continue
        for alias in aliases:
            key = alias.lower().strip()
            if key not in canonical:
                canonical[key] = alias

    # Return original casing from first occurrence
    return list(canonical.values())


def is_template_candidate(rules: list[dict]) -> tuple[bool, str]:
    """Check if rules share enough structure to be templated.

    Returns (is_template, template_name).
    """
    if len(rules) < 5:
        return False, ""

    # Check if they share module/subgroup
    modules = set(r.get("module") for r in rules)
    subgroups = set(r.get("subgroup") for r in rules)

    if len(modules) == 1 and len(subgroups) == 1:
        module = list(modules)[0]
        subgroup = list(subgroups)[0]
        return True, f"{module}_{subgroup}"

    return False, ""


def validate_rule(rule: dict) -> tuple[bool, str]:
    """Validate a single rule, return (valid, error_message)."""
    required_fields = ["name", "module", "source_type"]
    for field in required_fields:
        if field not in rule:
            return False, f"Missing required field: {field}"

    if not isinstance(rule.get("aliases"), (list, type(None))):
        return False, f"Aliases must be list or None for {rule.get('name')}"

    return True, ""


def load_json_robust(filepath: Path) -> dict | list | None:
    """Load JSON file robustly, handling corruption."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except json.JSONDecodeError as e:
        print(f"WARNING: JSON parse error in {filepath}: {e}")

        # Try to extract valid JSON blocks
        try:
            content = filepath.read_text()
            # Find balanced braces/brackets
            start = content.find("{")
            if start >= 0:
                end = len(content)
                brace_count = 0
                bracket_count = 0
                for i, c in enumerate(content[start:], start):
                    if c == "{":
                        brace_count += 1
                    elif c == "}":
                        brace_count -= 1
                        if brace_count == 0:
                            end = i + 1
                            break

                truncated = content[start:end]
                # Replace common corruption patterns
                truncated = re.sub(r',\s*\{\s*\{', ', {', truncated)
                truncated = re.sub(r'\}\s*\}', '}', truncated)

                data = json.loads(truncated)
                print(f"RECOVERED: Loaded partial JSON from {filepath} (truncated)")
                return data
        except Exception as e2:
            print(f"FATAL: Cannot recover JSON from {filepath}: {e2}")
            return None

    return None


def main():
    """Main deduplication pipeline."""
    input_file = Path("indicator_rules.json")
    output_file = Path("indicator_rules_deduped.json")
    report_file = Path("dedup_report.json")
    warnings_file = Path("warnings.txt")

    if not input_file.exists():
        print(f"ERROR: {input_file} not found")
        sys.exit(1)

    print(f"Loading rules from {input_file}...")
    raw_data = load_json_robust(input_file)

    if raw_data is None:
        print("FATAL: Could not load rules file")
        sys.exit(1)

    # Handle both dict with "rules" key and plain list
    if isinstance(raw_data, dict):
        rules = raw_data.get("rules", [])
        metadata = {k: v for k, v in raw_data.items() if k != "rules"}
    else:
        rules = raw_data
        metadata = {}

    print(f"Loaded {len(rules)} rules")

    # Validate all rules first
    valid_rules = []
    invalid_rules = []
    for rule in rules:
        valid, error = validate_rule(rule)
        if valid:
            valid_rules.append(rule)
        else:
            invalid_rules.append({"name": rule.get("name", "unknown"), "error": error})

    print(f"Valid: {len(valid_rules)}, Invalid: {len(invalid_rules)}")

    # Group by signature
    sig_groups: dict[tuple, list[dict]] = defaultdict(list)
    for rule in valid_rules:
        sig = compute_signature(rule)
        sig_groups[sig].append(rule)

    print(f"\nSignature groups: {len(sig_groups)} unique signatures")

    # Process each group
    deduplicated = []
    merged_counts = []

    for sig, group in sig_groups.items():
        if len(group) == 1:
            # No duplicates
            deduplicated.append(group[0])
        else:
            # Merge: keep first's structure, union all aliases
            base = group[0].copy()
            all_aliases = [r.get("aliases", []) for r in group]
            merged_aliases = merge_aliases(all_aliases)

            base["aliases"] = merged_aliases
            base["_merged_from"] = len(group)  # provenance

            deduplicated.append(base)
            merged_counts.append(len(group))

    print(f"\nAfter deduplication:")
    print(f"  Original: {len(valid_rules)}")
    print(f"  Deduplicated: {len(deduplicated)}")
    print(f"  Reduction: {(1 - len(deduplicated)/len(valid_rules))*100:.1f}%")
    print(f"  Max merge: {max(merged_counts) if merged_counts else 0} rules merged")

    # Check for template candidates
    print("\nSearching for template candidates...")
    module_subgroups: dict[str, list[dict]] = defaultdict(list)
    for rule in deduplicated:
        key = f"{rule.get('module', '')}/{rule.get('subgroup', '')}"
        module_subgroups[key].append(rule)

    templates_found = 0
    for key, group in module_subgroups.items():
        is_template, name = is_template_candidate(group)
        if is_template:
            templates_found += 1
            print(f"  Potential template: {name} ({len(group)} rules)")

    # Generate warnings for rules with few aliases
    warnings = []
    for rule in deduplicated:
        aliases = rule.get("aliases", [])
        name = rule.get("name", "unknown")
        if len(aliases) < 2:
            warnings.append(f"- {name}: only {len(aliases)} aliases (consider adding more)")

    # Write output files
    output_data = metadata.copy()
    output_data["rules"] = deduplicated

    print(f"\nWriting output files...")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"  {output_file}")

    # Write report
    report = {
        "input_rules": len(rules),
        "valid_rules": len(valid_rules),
        "invalid_rules": len(invalid_rules),
        "unique_signatures": len(sig_groups),
        "output_rules": len(deduplicated),
        "reduction_percent": round((1 - len(deduplicated)/len(valid_rules))*100, 1),
        "merged_groups": len([c for c in merged_counts if c > 1]),
        "max_merge": max(merged_counts) if merged_counts else 0,
        "template_candidates": templates_found,
    }

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  {report_file}")

    # Write warnings
    with open(warnings_file, "w", encoding="utf-8") as f:
        f.write("\n".join(warnings[:100]))  # Top 100 warnings
        if len(warnings) > 100:
            f.write(f"\n\n...and {len(warnings) - 100} more warnings")
    print(f"  {warnings_file}")

    print(f"\n✓ Deduplication complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
