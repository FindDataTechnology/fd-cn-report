# rule-gap-audit

## Purpose

Provide a repeatable audit loop that identifies indicator rules that are missing, unreachable, or frequently failing in LLM-based extraction, and outputs actionable fix suggestions (candidate sections, report forms, and priorities).

## ADDED Requirements

### Requirement: Audit identifies missing and failing indicators from rules and outputs
The system SHALL provide an audit entry point that reads the indicator rule set (`indicator_rules.json`) and one or more extraction output bundles (e.g., `out/*.json`) and produces an audit report.

The audit report SHALL classify each indicator into one or more categories:
- `missing_rule`: indicator appears in outputs or requested sets but has no resolvable rule (name/alias resolution fails)
- `inapplicable_rule`: a rule exists but is filtered out by `applies_to` for the company profile
- `missing_section`: a report rule exists but no selector resolves a section
- `unresolved_extractor`: extractor dispatch fails (e.g., unknown `python:<name>`), or extractor mode prevents execution
- `llm_null_value`: LLM executed but returned `null`/empty value for the indicator

#### Scenario: Missing section is surfaced from an output bundle
- **WHEN** an output bundle contains the indicator in `missing` with a note indicating selector misses
- **THEN** the audit classifies the indicator as `missing_section` and includes the selectors that were attempted.

### Requirement: Audit provides section suggestions based on a section map
When an indicator is classified as `missing_section`, the audit report SHALL provide a `suggested_sections` list derived from the section mapping capability (`report-section-map`) for the bundle's report form (annual/semiannual/quarterly).

#### Scenario: Suggested sections are attached for an annual-report miss
- **WHEN** an indicator is missing for `form="年度报告"`
- **THEN** the audit includes `suggested_sections` containing annual-report candidates such as “主要会计数据和财务指标” and “财务报表附注” (or their mapped aliases).

### Requirement: Audit output is machine-readable and stable
The audit entry point SHALL output a machine-readable JSON document containing:
- `generated_at`, `rules_hash`, `inputs` (paths scanned)
- `summary` (counts per category)
- `items[]` where each item contains `{indicator, categories[], companies/forms observed, evidence, suggested_sections}`

The output format SHALL be stable across runs so it can be used for regression comparison.

#### Scenario: Stable JSON schema is produced
- **WHEN** the audit runs on the same inputs twice
- **THEN** the output JSON parses successfully and preserves the same top-level keys and item structure.

