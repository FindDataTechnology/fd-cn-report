# indicator-lookup

## Purpose

Resolve a single named financial indicator to a value for a given company and period. The `get_indicator` tool selects the rule for the indicator, filters it by company applicability, resolves the section via the rule's `selectors[]` chain, and runs the rule's declared extractor (`"llm"`, `"python:<name>"`, a `computed` formula, or an `akshare` field read). Returns a uniform result object and never raises on failure.
## Requirements
### Requirement: Single indicator lookup via the applicable rule
The system SHALL provide a `get_indicator` tool that resolves one named financial indicator to a value for a given company (6-digit ticker or name fragment) and period. The system SHALL select the rule for that indicator, filter it by company applicability, resolve the section via the rule's `selectors[]` chain, and run the rule's declared extractor (`"llm"`, a script rule resolved via the extractor registry, a `computed` formula, or an `akshare` field read). The tool SHALL return a uniform result object and SHALL NOT raise on failure; it SHALL return `{"error": "..."}`.

#### Scenario: Bank-specific indicator via the LLM extractor
- **WHEN** `get_indicator(indicator="资本充足率", ticker_or_name="工商银行", year=2023)` is called
- **THEN** the system selects the 资本充足率 rule, confirms it applies to 工商银行, resolves the section via the company-specific selector (`三、资本充足率分析`) falling back to `资本充足率` then `风险管理`, fetches the cached PDF section, runs the `llm` extractor, and returns `{stock_code, company_name, year, indicator, value, unit, source_type: "report", extractor: "llm", source, period, provenance, pdf_url}`.

#### Scenario: Deterministic script extractor
- **WHEN** a rule has a matching `script_rules` row with `extract_rule: "regex_amount"`
- **THEN** the system dispatches to the registered `regex_amount` function with the section text + rule, returns its `{value, unit}` with `extractor: "script:regex_amount"`, and makes no LLM call.

#### Scenario: Computed ratio derived from base values
- **WHEN** `get_indicator(indicator="资产负债率", ticker_or_name="600519", year=2023)` is called for a `computed` rule
- **THEN** the system resolves each `inputs` base value (via akshare or already-extracted report values), evaluates `负债合计 / 资产总计` locally, and returns the result with `source_type: "computed"`, `extractor: "computed"`, and the `formula` in `source`.

#### Scenario: Company-specific section override
- **WHEN** the same indicator is requested for two banks whose rules carry different `selectors[]` entries with `company` filters
- **THEN** each bank resolves through its own first-matching selector, so the same indicator name is extracted from each bank's actual section title.

#### Scenario: Rule does not apply to the company
- **WHEN** the requested indicator's rule `applies_to` excludes the target company (e.g. a company-only indicator requested for a different company)
- **THEN** the system returns `{"error": "indicator not applicable to this company", "indicator": ..., "company": ...}` without fetching the PDF or calling the LLM.

#### Scenario: Unknown indicator name
- **WHEN** `get_indicator(indicator="不存在的指标", ...)` is called
- **THEN** the system returns `{"error": "unknown indicator: ...", "available": [<rule names, truncated>]}` without a network or LLM call.

#### Scenario: Section not located in the report
- **WHEN** no selector in the rule's `selectors[]` chain matches the parsed TOC, or the extractor returns no value
- **THEN** the system returns `{value: null, note: "...", source_type: "report", extractor: ..., ...}` (not an error), so the caller can distinguish "not found" from "failed".

### Requirement: Indicator name resolution with aliases
The system SHALL resolve an indicator name by exact match, then by an explicit `aliases` list, then by normalized substring (whitespace/punctuation-stripped) across the rule set. Resolution SHALL be whitespace-insensitive for Chinese names.

#### Scenario: Alias match
- **WHEN** a rule lists an alias and the caller passes that alias
- **THEN** the system resolves to that rule and proceeds with lookup.

#### Scenario: Whitespace-tolerant match
- **WHEN** the caller passes `" 资本充足率 "` (with surrounding spaces)
- **THEN** the system normalizes and resolves to the 资本充足率 rule.

### Requirement: Period handling
The system SHALL treat `year` as the fiscal year and SHALL default to the annual period. For `akshare`-sourced rules, the system SHALL pass `period` through to `financials_client.get_statements`. For `report`- and `computed`-sourced rules, the system SHALL select the annual report for the given `year`. Every successful result SHALL carry the resolved `period`.

#### Scenario: Annual period default
- **WHEN** `get_indicator` is called without `period`
- **THEN** the system uses the annual period (year-end for akshare; the year's 年度报告 PDF for report/computed).

### Requirement: Reuse the report cache
The system SHALL fetch annual-report PDFs through `report_cache.get_or_fetch` so that repeated `get_indicator` calls for the same company/year do not re-download or re-parse the PDF.

#### Scenario: Repeat call does not re-download
- **WHEN** `get_indicator` is called twice for the same company/year with different indicators
- **THEN** the PDF is downloaded and parsed at most once; the second call reads cached text.

### Requirement: Consistent error contract
The system SHALL wrap `get_indicator` in the existing `@_tool_safe` decorator so any unexpected exception becomes `{"error": "<Type>: <msg>"}`, matching the contract of `get_financials` / `get_section`.

#### Scenario: Underlying failure surfaces as error
- **WHEN** an akshare or HTTP failure occurs during lookup
- **THEN** the tool returns `{"error": "..."}` and does not raise.

