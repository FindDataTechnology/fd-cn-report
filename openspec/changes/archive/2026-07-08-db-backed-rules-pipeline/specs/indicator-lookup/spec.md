## MODIFIED Requirements

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
