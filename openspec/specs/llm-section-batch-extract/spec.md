# llm-section-batch-extract Specification

## Purpose
Batch LLM extraction that groups all report-type indicators sharing the same resolved section into a single LLM call per module, reducing API calls from N (one per indicator) to M (one per section × module).
## Requirements

### Requirement: Batch LLM extraction groups all report indicators by section
The system SHALL group all `report`-type rules sharing the same resolved section into a single LLM call per module. For each resolved section, the system SHALL collect every applicable report rule (regardless of former `extractor` field), partition them by Pydantic module (`balance_sheet`, `income_statement`, `cashflow`, `report_section`), and make one `_llm_extract_section` call per module. The system SHALL NOT split rules into `llm_rules` and `python_rules` groups within a section — all report rules in a section are LLM-extracted together.

#### Scenario: All report rules in one section go to one LLM call
- **WHEN** three `report` rules (`资产负债表` module) and two `report` rules (`income_statement` module) all resolve to the same section `"合并资产负债表"`
- **THEN** the system makes exactly two LLM calls: one for the `balance_sheet` module (3 fields) and one for the `income_statement` module (2 fields), and no per-indicator calls.

#### Scenario: Section with mixed modules
- **WHEN** a section contains both `balance_sheet` and `report_section` rules
- **THEN** the system makes two LLM calls (one per module), each receiving only its own module's rules as fields.
