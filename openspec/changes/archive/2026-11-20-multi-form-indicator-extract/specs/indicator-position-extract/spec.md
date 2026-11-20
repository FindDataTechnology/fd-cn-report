## MODIFIED Requirements

### Requirement: CSV-driven extraction by position catalog
The system SHALL provide an `extract_indicators_by_position` tool that extracts the indicators named in a position CSV for one company (6-digit ticker or name fragment) and fiscal year. The default CSV SHALL be `docs/indicators_position.csv`; a `csv_path` argument SHALL allow selecting an alternate position file. The tool SHALL read the CSV's `indicator` column to determine the target indicator set, intersect it with the optional `indicators` argument if given, resolve each name to a rule in the merged `indicator_rules.json` (name → alias → normalized substring), and route each resolved rule through the existing `extract_indicators` batch engine (one PDF fetch, batched LLM per section, python extractors, computed ratios, bundle cache). The tool SHALL accept a `form` argument selecting the CNINFO periodic report form (`年度报告` default, `半年度报告`, `第一季度报告`, `第三季度报告`); the form SHALL flow through to `extract_indicators(form=…)`. The tool SHALL be wrapped in `@_tool_safe` so failures become `{"error": "..."}`.

#### Scenario: Extract all indicators named in the default CSV
- **WHEN** `extract_indicators_by_position(ticker_or_name="工商银行", year=2023)` is called
- **THEN** the system reads `docs/indicators_position.csv`, resolves each `indicator` to a rule, routes `report`/`akshare`/`computed` rules through the batch engine, classifies `external` rules into `skipped`, and returns the result map plus `missing`, `unresolved`, and `skipped` lists.

#### Scenario: Alternate position CSV
- **WHEN** `extract_indicators_by_position(ticker_or_name="工商银行", year=2023, csv_path="docs/my_subset.csv")` is called
- **THEN** the system reads the indicator set from `docs/my_subset.csv` instead of the default and records `csv_path` in the result provenance.

#### Scenario: Indicator subset intersection
- **WHEN** `extract_indicators_by_position(ticker_or_name="工商银行", year=2023, indicators=["资产总计", "负债合计"])` is called
- **THEN** the system extracts exactly those two indicators (those present in the CSV) after applicability filtering, and returns only those keys.

#### Scenario: Unknown indicator name in the CSV
- **WHEN** the CSV's `indicator` column contains a name that does not resolve in the merged rule set
- **THEN** the system includes that name in `missing` with a `reason: "unknown indicator"` note and continues with the rest, rather than failing the whole call.

#### Scenario: Quarterly form fetches the Q1 report
- **WHEN** `extract_indicators_by_position(ticker_or_name="600519", year=2023, form="第一季度报告")` is called
- **THEN** the system fetches the 2023 Q1 report PDF (not the annual), records `form: "第一季度报告"` in the bundle, and the `pdf_url` points to the Q1 announcement.

### Requirement: External indicators are skipped, not fetched
The system SHALL partition the resolved indicator set by `source_type` before extraction. Rules with `source_type: "external"` (realtime / market-data indicators not present in the report PDF) SHALL be placed in a `skipped` list with a note (`realtime/external — not in report PDF`) and SHALL NOT trigger a PDF fetch, akshare call, or LLM call. Rules with `source_type: "report"`, `"akshare"`, or `"computed"` SHALL be routed through the batch engine. Additionally, rules whose `report_type` field does not contain the chosen form's compatibility key (`年报`/`半年报`/`季报`) SHALL be placed in `skipped` with `source_type: "form_filter"` and `note: f"not in {form}"` before any PDF fetch; rules without a `report_type` field SHALL default to broadly applicable (`年报/半年报/季报`) and not be skipped.

#### Scenario: Realtime market indicator is skipped
- **WHEN** the CSV names `PE-TTM` (an `external` rule) for extraction
- **THEN** `PE-TTM` appears in `skipped` with note `realtime/external — not in report PDF`, no PDF is fetched for it, and no LLM call is made for it.

#### Scenario: Report indicator is extracted, external is skipped
- **WHEN** the CSV names both `资产总计` (`report`) and `PB` (`external`)
- **THEN** `资产总计` is resolved through the batch engine and appears in `indicators`, while `PB` appears in `skipped`.

#### Scenario: Annual-only indicator skipped for quarterly form
- **WHEN** `extract_indicators_by_position(ticker_or_name="600519", year=2023, form="第一季度报告")` is called and the CSV names `分红金额` (report_type `年报`)
- **THEN** `分红金额` appears in `skipped` with `source_type: "form_filter"` and `note` containing `not in 第一季度报告`, and no PDF fetch or LLM call is attempted for it.

### Requirement: Result shape and provenance
The system SHALL return `{stock_code, company_name, year, form, pdf_url, cached, indicators: {...}, missing: [...], unresolved: [...], skipped: [...], csv_path}`. Each `indicators` entry SHALL carry `value`, `unit`, `source_type`, `extractor`, `source`, `period`, and `provenance`. The `csv_path` field SHALL record the position file used. The `form` field SHALL record the CNINFO form used. The `skipped` array SHALL list `{indicator, source_type, note}` entries (including both `external` and `form_filter` skips).

#### Scenario: Full result shape on success
- **THEN** the returned object contains the company/year header fields (including `form`), the `indicators` map, the `missing`, `unresolved`, and `skipped` arrays (empty when nothing is missing/skipped), and `csv_path`.

#### Scenario: Non-bank company served
- **WHEN** `extract_indicators_by_position(ticker_or_name="600519", year=2023)` is called for a non-bank company
- **THEN** universal CSV rules (`applies_to.industry: "*"`) are extracted from the 2023 annual report, bank-scoped rules are excluded via applicability, and the result header carries the non-bank company profile.
