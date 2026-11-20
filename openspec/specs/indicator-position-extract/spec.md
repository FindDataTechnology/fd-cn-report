# indicator-position-extract Specification

## Purpose
TBD - created by archiving change extract-indicators-by-position. Update Purpose after archive.

## Requirements

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

### Requirement: Extractor mode override
The tool SHALL accept an `extractor` argument (`"auto"` | `"llm"` | `"python"`, default `"auto"`) with the same semantics as the extraction script: `auto` uses each rule's declared extractor; `python` skips `report`-type rules whose declared extractor is `"llm"` (placing them in `unresolved`); `llm` forces the LLM extractor for `report`-type rules.

#### Scenario: Python mode skips llm-only report rules
- **WHEN** `extract_indicators_by_position(..., extractor="python")` is called and a `report` rule declares `extractor: "llm"`
- **THEN** that rule is listed in `unresolved` with note `skipped: llm extractor in python mode` and no LLM call is made.

### Requirement: Result shape and provenance
The system SHALL return `{stock_code, company_name, year, form, pdf_url, cached, indicators: {...}, missing: [...], unresolved: [...], skipped: [...], csv_path}`. Each `indicators` entry SHALL carry `value`, `unit`, `source_type`, `extractor`, `source`, `period`, and `provenance`. The `csv_path` field SHALL record the position file used. The `form` field SHALL record the CNINFO form used. The `skipped` array SHALL list `{indicator, source_type, note}` entries (including both `external` and `form_filter` skips).

#### Scenario: Full result shape on success
- **THEN** the returned object contains the company/year header fields (including `form`), the `indicators` map, the `missing`, `unresolved`, and `skipped` arrays (empty when nothing is missing/skipped), and `csv_path`.

#### Scenario: Non-bank company served
- **WHEN** `extract_indicators_by_position(ticker_or_name="600519", year=2023)` is called for a non-bank company
- **THEN** universal CSV rules (`applies_to.industry: "*"`) are extracted from the 2023 annual report, bank-scoped rules are excluded via applicability, and the result header carries the non-bank company profile.

### Requirement: Reuse the batch engine, no logic duplication
The tool SHALL delegate extraction to `indicators_client.extract_indicators` (or its building blocks) and `report_cache` — it SHALL NOT reimplement PDF fetching, section resolution, extractor dispatch, computation, or caching. The CSV is used only to select the indicator set and classify `external` entries.

#### Scenario: Engine reuse
- **WHEN** the tool runs
- **THEN** it calls `indicators_client.extract_indicators(...)` for the non-external subset and `report_cache.get_or_fetch` indirectly through it, and contains no independent PDF/LLM/caching code.

### Requirement: Section resolution walks the selector chain with statement-table priority
For `report` rules in the `balance_sheet`, `income_statement`, or `cashflow` modules, the system SHALL resolve the section by walking `selectors[]` in order, expanding each `selector.section` through the section map's alias candidates. When a selector like `资产负债表` would match an MD&A analysis sub-section (e.g. `7.2.2 资产负债表项目分析`) via substring, the system SHALL first try the canonical consolidated statement title (`合并资产负债表` / `合并利润表` / `合并现金流量表`) as an expanded candidate before falling back to the MD&A match. The batch extraction path in `extract_indicators` SHALL pass `form=ctx.form` to `_resolve_section` so the section map is form-aware.

#### Scenario: Balance sheet selector resolves to the statement table, not MD&A
- **WHEN** a `balance_sheet` rule declares `selectors: [{section: "资产负债表"}]` and the outline contains both `"7.2.2 资产负债表项目分析"` and `"合并及公司资产负债表"`
- **THEN** the resolved section is the consolidated statement table (not the MD&A analysis), and the LLM receives the actual financial data.

#### Scenario: Form is passed to section resolution in batch path
- **WHEN** `extract_indicators` is called with `form="半年度报告"`
- **THEN** `_resolve_section` receives `form="半年度报告"` and the section map returns semiannual-specific aliases.

### Requirement: Position-extraction result includes section evidence when available
When extracting `report`-type indicators by position, the system SHALL attach section evidence to each extracted indicator when the information is available from the report cache or outline resolver. Evidence SHALL include the matched section title and MAY include page range or a short heading snippet.

#### Scenario: Evidence includes matched section title
- **WHEN** an indicator is extracted from a resolved section
- **THEN** its provenance includes the matched section title that was used to source the section text.

### Requirement: Missing-section indicators include attempted candidates
When a `report`-type indicator is missing because no selector matched any report section, the system SHALL record the attempted section candidates (after section-map expansion) in the `missing` list entry to support rule debugging.

#### Scenario: Missing records attempted candidates
- **WHEN** a report indicator misses section resolution
- **THEN** the `missing` entry includes the list of attempted section titles.
