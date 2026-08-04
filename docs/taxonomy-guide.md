# Taxonomy System Guide

## Overview

The taxonomy system provides a standardized, multi-language classification framework for financial report rules. It replaces the previous free-text `module`/`subgroup`/`document_type` fields with structured taxonomy codes.

## Key Concepts

### Report Taxonomy (report_taxonomy)

Hierarchical classification of report content sections:

```
Level 1: Top-level categories
  - financial_statements (财务报表)
  - report_sections (报告章节)
  - prospectus_sections (招股书章节)

Level 2: Specific sections
  - balance_sheet (资产负债表)
  - income_statement (利润表)
  - cashflow_statement (现金流量表)
  - risk_factors (风险因素)
  - ...

Level 3: Sub-sections
  - balance_sheet.current_assets (流动资产)
  - balance_sheet.non_current_assets (非流动资产)
  - income_statement.revenue (营业收入)
  - ...
```

### Document Taxonomy (document_taxonomy)

Classification of document types by market and report kind:

```
Level 1: Market categories
  - cn_periodic (A股定期报告)
  - hk_periodic (港股定期报告)
  - prospectus (招股说明书)
  - ...

Level 2: Specific document types
  - cn_annual (A股年报)
  - cn_interim (A股半年报)
  - cn_quarterly (A股季报)
  - hk_annual (港股年报)
  - ...
```

## Multi-Language Support

All taxonomy entries support four languages:
- `label_zh`: Chinese (required)
- `label_en`: English (required)
- `label_ja`: Japanese (optional)
- `label_ko`: Korean (optional)

Example:
```python
balance_sheet = {
    "code": "balance_sheet",
    "label_zh": "资产负债表",
    "label_en": "Balance Sheet",
    "label_ja": "貸借対照表",
    "label_ko": "대차대조표"
}
```

## Usage

### Querying Taxonomy

```python
import rules_db

# List top-level report taxonomy
top_level = rules_db.list_report_taxonomy(parent_code=None)

# Get specific taxonomy entry
balance_sheet = rules_db.get_report_taxonomy("balance_sheet")

# Get children of a taxonomy node
children = rules_db.get_report_taxonomy_children("financial_statements")

# List document taxonomy
doc_types = rules_db.list_document_taxonomy()

# Filter by country
cn_types = rules_db.list_document_taxonomy(country="cn")
```

### Filtering Rules

```python
# Load rules with new structure
rules = rules_db.load_rules()["rules"]

# Filter by taxonomy_code
balance_sheet_rules = [
    r for r in rules 
    if r.get("taxonomy_code", "").startswith("balance_sheet")
]

# Filter by document_type_codes
cn_annual_rules = [
    r for r in rules 
    if "cn_annual" in r.get("document_type_codes", [])
]
```

## Adding New Taxonomy Entries

### Adding Report Taxonomy

```python
from cnreport_models import ReportTaxonomy
import rules_db

with rules_db._session() as session:
    new_entry = ReportTaxonomy(
        code="esg_report",
        parent_code="report_sections",
        level=2,
        label_zh="ESG报告",
        label_en="ESG Report",
        label_ja="ESGレポート",
        label_ko="ESG 보고서",
        description="Environmental, Social, and Governance report",
        sort_order=300
    )
    session.add(new_entry)
    session.commit()
```

### Adding Document Taxonomy

```python
from cnreport_models import DocumentTaxonomy
import rules_db

with rules_db._session() as session:
    new_entry = DocumentTaxonomy(
        code="us_10k",
        parent_code="us_periodic",
        level=2,
        label_zh="美国10-K年报",
        label_en="US 10-K Annual Report",
        country="us",
        exchange="sec",
        report_kind="annual",
        sort_order=100
    )
    session.add(new_entry)
    session.commit()
```

## Migration from Old System

The migration from the old `module`/`subgroup`/`document_type` system to the new taxonomy system was completed on 2026-08-04.

### Old Structure
```python
{
    "name": "营业收入",
    "module": "income_statement",
    "subgroup": "营业收入",
    "document_types": ["cn/801780/listed/annual-report"]
}
```

### New Structure
```python
{
    "name": "营业收入",
    "taxonomy_code": "income_statement.revenue",
    "document_type_codes": ["cn_annual"],
    "indicator_translations": {
        "zh": "营业收入",
        "en": "Revenue",
        "ja": "収益",
        "ko": "매출액"
    }
}
```

## Benefits

1. **Standardization**: Consistent classification across all rules
2. **Multi-language**: Support for international users
3. **Hierarchical**: Parent-child relationships enable flexible querying
4. **Extensible**: Easy to add new categories and languages
5. **Type-safe**: Structured codes instead of free text

## API Reference

### rules_db Functions

- `list_report_taxonomy(parent_code=None)`: List report taxonomy entries
- `get_report_taxonomy(code)`: Get specific report taxonomy entry
- `get_report_taxonomy_children(code)`: Get children of a taxonomy node
- `list_document_taxonomy(parent_code=None, country=None)`: List document taxonomy entries
- `get_document_taxonomy(code)`: Get specific document taxonomy entry
- `get_document_taxonomy_children(code)`: Get children of a document taxonomy node

### Database Tables

- `report_taxonomy`: Report content classification
- `document_taxonomy`: Document type classification
- `llm_rules`: Rules with taxonomy references

## Troubleshooting

### Missing Taxonomy Code

If a rule has `taxonomy_code: null`, it means the rule hasn't been mapped to the new taxonomy yet. Run the migration script to map existing rules.

### Missing Translations

If a taxonomy entry is missing translations for a language, the system will fall back to the Chinese label. Add missing translations by updating the taxonomy entry.

### Query Performance

For large rule sets, consider adding indexes on frequently queried taxonomy codes:

```sql
CREATE INDEX idx_llm_rules_taxonomy_code ON llm_rules(taxonomy_code);
CREATE INDEX idx_llm_rules_document_type_codes ON llm_rules(document_type_codes);
```
