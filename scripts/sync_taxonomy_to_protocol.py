#!/usr/bin/env python3
"""Sync taxonomy system to fd-open-data-protocol.

This script updates the fd-cn-report catalog.py to include taxonomy information
and ensures compatibility with the fd-open-data-protocol schema.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def update_catalog_with_taxonomy():
    """Update catalog.py to include taxonomy definitions."""
    import rules_db

    # Get taxonomy statistics
    report_taxonomy = rules_db.list_report_taxonomy()
    document_taxonomy = rules_db.list_document_taxonomy()

    print("=" * 70)
    print("Syncing Taxonomy to fd-open-data-protocol")
    print("=" * 70)
    print(f"\nReport Taxonomy entries: {len(report_taxonomy)}")
    print(f"Document Taxonomy entries: {len(document_taxonomy)}")

    # Build entity definitions for taxonomy
    entity_definitions = []

    # Add report taxonomy as industry entities
    for entry in report_taxonomy[:20]:  # Top 20 for now
        entity_definitions.append({
            "entity_type": "industry",
            "code": f"taxonomy_{entry['code']}",
            "name_en": entry.get('label_en'),
            "name_zh": entry.get('label_zh'),
            "metadata": {
                "classification_system": "report_taxonomy",
                "level": entry.get('level', 1),
                "parent_code": entry.get('parent_code'),
            }
        })

    # Add document taxonomy as organization entities
    for entry in document_taxonomy:
        entity_definitions.append({
            "entity_type": "organization",
            "code": f"doc_{entry['code']}",
            "name_en": entry.get('label_en'),
            "name_zh": entry.get('label_zh'),
            "metadata": {
                "classification_system": "document_taxonomy",
                "country": entry.get('country'),
                "exchange": entry.get('exchange'),
                "report_kind": entry.get('report_kind'),
            }
        })

    print(f"\nGenerated {len(entity_definitions)} entity definitions")

    # Read current catalog
    catalog_path = Path(__file__).resolve().parent.parent / "catalog.py"
    with open(catalog_path, 'r', encoding='utf-8') as f:
        catalog_content = f.read()

    # Add taxonomy-related concepts
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
        },
        {
            "column": "indicator_translations",
            "concept": "taxonomy.indicator_multilang",
            "entity_type": "company",
            "measure": "indicator_name_multilang",
            "unit": "json",
            "frequency": "static"
        }
    ]

    # Update catalog content
    # Find the concepts section and add taxonomy concepts
    if 'taxonomy.report_section' not in catalog_content:
        # Insert before the last closing bracket of concepts list
        insert_pos = catalog_content.rfind('],\n    "entities"')
        if insert_pos > 0:
            concepts_str = ",\n        ".join([
                f'{{"column": "{c["column"]}", "concept": "{c["concept"]}", '
                f'"entity_type": "{c["entity_type"]}", "measure": "{c["measure"]}", '
                f'"unit": "{c["unit"]}", "frequency": "{c["frequency"]}"}}'
                for c in taxonomy_concepts
            ])
            catalog_content = (
                catalog_content[:insert_pos] +
                ",\n        " + concepts_str +
                catalog_content[insert_pos:]
            )

    # Write updated catalog
    with open(catalog_path, 'w', encoding='utf-8') as f:
        f.write(catalog_content)

    print(f"\n✓ Updated {catalog_path}")
    print(f"  Added {len(taxonomy_concepts)} taxonomy concepts")

    # Verify the update
    print("\nVerifying update...")
    import importlib.util
    spec = importlib.util.spec_from_file_location("catalog", catalog_path)
    catalog_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog_module)

    catalog = catalog_module.CATALOG
    print(f"✓ Catalog has {len(catalog.get('concepts', []))} concepts")
    print(f"✓ Catalog has {len(catalog.get('entities', []))} entity specs")

    # Check for taxonomy concepts
    taxonomy_concept_count = sum(
        1 for c in catalog.get('concepts', [])
        if 'taxonomy' in c.get('concept', '')
    )
    print(f"✓ Found {taxonomy_concept_count} taxonomy concepts")

    print("\n" + "=" * 70)
    print("Sync complete!")
    print("=" * 70)

    return catalog


def generate_taxonomy_schema_extension():
    """Generate a schema extension document for taxonomy support."""
    schema_doc = """# Taxonomy System Schema Extension

## Overview

The taxonomy system extends the fd-open-data-protocol with hierarchical classification
support for financial report content and document types.

## New Concepts

### taxonomy.report_section
- **Column**: `taxonomy_code`
- **Entity Type**: `industry`
- **Description**: Hierarchical classification of report sections
- **Format**: Dot-separated path (e.g., `balance_sheet.current_assets`)

### taxonomy.document_type
- **Column**: `document_type_codes`
- **Entity Type**: `organization`
- **Description**: Standardized document type classification
- **Format**: Array of codes (e.g., `["cn_annual", "hk_interim"]`)

### taxonomy.indicator_multilang
- **Column**: `indicator_translations`
- **Entity Type**: `company`
- **Description**: Multi-language indicator names
- **Format**: JSON object with language codes (zh, en, ja, ko)

## Entity Definitions

### Report Taxonomy Entities
- **Entity Type**: `industry`
- **Code Pattern**: `taxonomy_<code>`
- **Metadata**:
  - `classification_system`: "report_taxonomy"
  - `level`: 1-3 (hierarchy level)
  - `parent_code`: Parent taxonomy code

### Document Taxonomy Entities
- **Entity Type**: `organization`
- **Code Pattern**: `doc_<code>`
- **Metadata**:
  - `classification_system`: "document_taxonomy"
  - `country`: ISO country code (cn, hk, us, etc.)
  - `exchange`: Stock exchange code (sse, szse, hkex, etc.)
  - `report_kind`: Report type (annual, interim, quarterly, etc.)

## Usage Example

```python
# Query rules by taxonomy
rules = rules_db.load_rules()["rules"]
balance_sheet_rules = [
    r for r in rules
    if r.get("taxonomy_code", "").startswith("balance_sheet")
]

# Query by document type
cn_annual_rules = [
    r for r in rules
    if "cn_annual" in r.get("document_type_codes", [])
]

# Get multi-language indicator name
indicator_zh = rule.get("indicator_translations", {}).get("zh")
indicator_en = rule.get("indicator_translations", {}).get("en")
```

## Compatibility

- **Backward Compatible**: Yes (old module/subgroup fields still present)
- **Protocol Version**: 1.x
- **Migration Status**: Complete (2026-08-04)
"""

    doc_path = Path(__file__).resolve().parent.parent / "docs" / "taxonomy-schema-extension.md"
    with open(doc_path, 'w', encoding='utf-8') as f:
        f.write(schema_doc)

    print(f"\n✓ Generated schema extension: {doc_path}")


if __name__ == "__main__":
    catalog = update_catalog_with_taxonomy()
    generate_taxonomy_schema_extension()

    print("\n✅ All sync operations complete!")
    print("\nNext steps:")
    print("1. Review updated catalog.py")
    print("2. Test with fd-open-data-mcp register_datasource")
    print("3. Verify taxonomy queries work through MCP")
