# Taxonomy System Schema Extension

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
