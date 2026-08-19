#!/usr/bin/env python3
"""Sync all datasources to unified taxonomy system.

This script updates all fd-* datasources with consistent taxonomy concepts
and ensures fd-open-data-protocol compliance.
"""
import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def update_fd_cn_gov():
    """Update fd-cn-gov catalog with taxonomy concepts."""
    catalog_path = Path('/Users/chengsishi/finddata/fd-cn-gov/fd_cn_gov/catalog.py')

    print("\nfd-cn-gov:")
    print("-" * 70)

    # Read current catalog
    with open(catalog_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the concepts section
    concepts_start = content.find('"concepts": [')
    concepts_end = content.find('],\n    "entities"')

    if concepts_start == -1 or concepts_end == -1:
        print("  ✗ Could not find concepts section")
        return False

    # Parse current concepts
    concepts_section = content[concepts_start:concepts_end+3]
    concepts_json = concepts_section.replace('"concepts": [', '[').rstrip('],')
    try:
        concepts = json.loads(concepts_json + ']')
    except:
        print("  ✗ Could not parse concepts")
        return False

    print(f"  Current concepts: {len(concepts)}")

    # Check if taxonomy concepts already exist
    has_taxonomy = any('taxonomy' in c.get('concept', '') for c in concepts)
    if has_taxonomy:
        print("  ✓ Already has taxonomy concepts")
        return False

    # Add taxonomy concepts
    taxonomy_concepts = [
        {
            "column": "taxonomy_code",
            "concept": "taxonomy.report_section",
            "entity_type": "industry",
            "measure": "report_section_classification",
            "unit": "string",
            "frequency": "static"
        },
        {
            "column": "document_type_codes",
            "concept": "taxonomy.document_type",
            "entity_type": "organization",
            "measure": "document_type_classification",
            "unit": "array",
            "frequency": "static"
        }
    ]

    all_concepts = concepts + taxonomy_concepts
    print(f"  Adding {len(taxonomy_concepts)} taxonomy concepts")

    # Build new concepts section
    new_concepts_section = '"concepts": [\n    ' + ',\n    '.join(json.dumps(c) for c in all_concepts) + '\n  ]'

    # Replace in content
    new_content = content[:concepts_start] + new_concepts_section + content[concepts_end+3:]

    # Write back
    with open(catalog_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    print(f"  ✓ Updated {catalog_path}")
    return True


def update_fd_world():
    """Update fd-world catalog with taxonomy concepts."""
    catalog_path = Path('/Users/chengsishi/finddata/fd-world/fd_world/catalog.py')

    print("\nfd-world:")
    print("-" * 70)

    # Read current catalog
    with open(catalog_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the concepts section
    concepts_start = content.find('"concepts": [')
    concepts_end = content.find('],\n    "entities"')

    if concepts_start == -1 or concepts_end == -1:
        print("  ✗ Could not find concepts section")
        return False

    # Parse current concepts
    concepts_section = content[concepts_start:concepts_end+3]
    concepts_json = concepts_section.replace('"concepts": [', '[').rstrip('],')
    try:
        concepts = json.loads(concepts_json + ']')
    except:
        print("  ✗ Could not parse concepts")
        return False

    print(f"  Current concepts: {len(concepts)}")

    # Check if taxonomy concepts already exist
    has_taxonomy = any('taxonomy' in c.get('concept', '') for c in concepts)
    if has_taxonomy:
        print("  ✓ Already has taxonomy concepts")
        return False

    # Add taxonomy concepts
    taxonomy_concepts = [
        {
            "column": "taxonomy_code",
            "concept": "taxonomy.report_section",
            "entity_type": "industry",
            "measure": "report_section_classification",
            "unit": "string",
            "frequency": "static"
        },
        {
            "column": "document_type_codes",
            "concept": "taxonomy.document_type",
            "entity_type": "organization",
            "measure": "document_type_classification",
            "unit": "array",
            "frequency": "static"
        }
    ]

    all_concepts = concepts + taxonomy_concepts
    print(f"  Adding {len(taxonomy_concepts)} taxonomy concepts")

    # Build new concepts section
    new_concepts_section = '"concepts": [\n    ' + ',\n    '.join(json.dumps(c) for c in all_concepts) + '\n  ]'

    # Replace in content
    new_content = content[:concepts_start] + new_concepts_section + content[concepts_end+3:]

    # Write back
    with open(catalog_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    print(f"  ✓ Updated {catalog_path}")
    return True


def main():
    """Main sync function."""
    print('=' * 70)
    print("Syncing All Datasources to Unified Taxonomy System")
    print('=' * 70)

    updated_count = 0

    try:
        if update_fd_cn_gov():
            updated_count += 1
    except Exception as e:
        print(f"  ✗ Error updating fd-cn-gov: {e}")

    try:
        if update_fd_world():
            updated_count += 1
    except Exception as e:
        print(f"  ✗ Error updating fd-world: {e}")

    print("\n" + '=' * 70)
    print(f"✅ Sync complete! Updated {updated_count}/2 datasources")
    print('=' * 70)


if __name__ == "__main__":
    main()
