## ADDED Requirements

### Requirement: CSV-driven extraction by position catalog
The system SHALL provide an `extract_indicators_by_position` tool that extracts the indicators named in a position CSV for one company (6-digit ticker or name fragment) and fiscal year. The default CSV SHALL be `docs/indicators_position.csv`; a `csv_path` argument SHALL allow selecting an alternate position file. The tool SHALL read the CSV's `indicator` column to determine the target indicator set, intersect it with the optional `indicators` argument if given, resolve each name to a rule in the merged `indicator_rules.json` (name → alias → normalized substring), and route each resolved rule through the existing `extract_indicators` batch engine (one PDF fetch, batched LLM per section, python extractors, computed ratios, bundle cache). The tool SHALL be wrapped in `@_tool_safe` so failures become `{"error": "..."}`.

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

### Requirement: External indicators are skipped, not fetched
The system SHALL partition the resolved indicator set by `source_type` before extraction. Rules with `source_type: "external"` (realtime / market-data indicators not present in the report PDF) SHALL be placed in a `skipped` list with a note (`realtime/external — not in report PDF`) and SHALL NOT trigger a PDF fetch, akshare call, or LLM call. Rules with `source_type: "report"`, `"akshare"`, or `"computed"` SHALL be routed through the batch engine.

#### Scenario: Realtime market indicator is skipped
- **WHEN** the CSV names `PE-TTM` (an `external` rule) for extraction
- **THEN** `PE-TTM` appears in `skipped` with note `realtime/external — not in report PDF`, no PDF is fetched for it, and no LLM call is made for it.

#### Scenario: Report indicator is extracted, external is skipped
- **WHEN** the CSV names both `资产总计` (`report`) and `PB` (`external`)
- **THEN** `资产总计` is resolved through the batch engine and appears in `indicators`, while `PB` appears in `skipped`.

### Requirement: Extractor mode override
The tool SHALL accept an `extractor` argument (`"auto"` | `"llm"` | `"python"`, default `"auto"`) with the same semantics as the extraction script: `auto` uses each rule's declared extractor; `python` skips `report`-type rules whose declared extractor is `"llm"` (placing them in `unresolved`); `llm` forces the LLM extractor for `report`-type rules.

#### Scenario: Python mode skips llm-only report rules
- **WHEN** `extract_indicators_by_position(..., extractor="python")` is called and a `report` rule declares `extractor: "llm"`
- **THEN** that rule is listed in `unresolved` with note `skipped: llm extractor in python mode` and no LLM call is made.

### Requirement: Result shape and provenance
The system SHALL return `{stock_code, company_name, year, form, pdf_url, cached, indicators: {...}, missing: [...], unresolved: [...], skipped: [...], csv_path}`. Each `indicators` entry SHALL carry `value`, `unit`, `source_type`, `extractor`, `source`, `period`, and `provenance`. The `csv_path` field SHALL record the position file used. The `skipped` array SHALL list `{indicator, source_type, note}` entries.

#### Scenario: Full result shape on success
- **THEN** the returned object contains the company/year header fields, the `indicators` map, the `missing`, `unresolved`, and `skipped` arrays (empty when nothing is missing/skipped), and `csv_path`.

#### Scenario: Non-bank company served
- **WHEN** `extract_indicators_by_position(ticker_or_name="600519", year=2023)` is called for a non-bank company
- **THEN** universal CSV rules (`applies_to.industry: "*"`) are extracted from the 2023 annual report, bank-scoped rules are excluded via applicability, and the result header carries the non-bank company profile.

### Requirement: Reuse the batch engine, no logic duplication
The tool SHALL delegate extraction to `indicators_client.extract_indicators` (or its building blocks) and `report_cache` — it SHALL NOT reimplement PDF fetching, section resolution, extractor dispatch, computation, or caching. The CSV is used only to select the indicator set and classify `external` entries.

#### Scenario: Engine reuse
- **WHEN** the tool runs
- **THEN** it calls `indicators_client.extract_indicators(...)` for the non-external subset and `report_cache.get_or_fetch` indirectly through it, and contains no independent PDF/LLM/caching code.
