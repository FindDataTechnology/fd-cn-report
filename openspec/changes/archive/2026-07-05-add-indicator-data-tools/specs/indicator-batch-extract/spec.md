## ADDED Requirements

### Requirement: Batch extract all applicable indicators in one pass
The system SHALL provide an `extract_indicators` tool that, for one company and fiscal year, returns the values of many indicators at once. The system SHALL first compute the rules applicable to that company (`applicable_rules`) and SHALL attempt only those — indicators whose rules do not apply are excluded, not errored. When `indicators` is omitted, the system SHALL attempt every applicable rule; when `indicators` is a list, it SHALL attempt exactly those (after applicability filtering). The tool SHALL return `{indicator: {value, unit, source, source_type, extractor, period, provenance}}` plus `missing` and `unresolved` lists.

#### Scenario: Extract every applicable indicator
- **WHEN** `extract_indicators(ticker_or_name="工商银行", year=2023)` is called
- **THEN** the system returns a result map keyed by indicator name for every applicable rule it could resolve, with `source_type` and `extractor` per entry, and excludes rules that do not apply to 工商银行.

#### Scenario: Extract a selected subset
- **WHEN** `extract_indicators(ticker_or_name="工商银行", year=2023, indicators=["资本充足率", "不良率", "资产负债率"])` is called
- **THEN** the system resolves exactly those three (subject to applicability) and returns only those keys.

#### Scenario: Non-applicable indicator in a selected subset
- **WHEN** `indicators` contains an indicator whose rule does not apply to the target company
- **THEN** the system includes that name in `missing` with a `reason: "not applicable"` note and continues with the rest.

#### Scenario: Unknown name in a selected subset
- **WHEN** `indicators` contains a name that does not resolve in the rule set
- **THEN** the system includes that name in `missing` and continues with the rest, rather than failing the whole call.

### Requirement: One PDF fetch per company/year
The system SHALL fetch the annual-report PDF at most once per `extract_indicators` call, regardless of how many indicators are requested, by reusing `report_cache.get_or_fetch` and the already-extracted section text across all `report`-type rules.

#### Scenario: Single fetch for many report indicators
- **WHEN** ten `report`-type rules map to three distinct sections
- **THEN** the PDF is downloaded/parsed once and each distinct section's text is fetched once (cache-backed); no per-indicator PDF re-read occurs.

### Requirement: Group LLM extraction by section; dispatch Python extractors individually
For `report`-type rules, the system SHALL sub-partition the applicable rules by their resolved section. Rules with `extractor: "llm"` SHALL be batched into one `ai_extract` call per distinct section, requesting all such indicators in a single schema. Rules with `extractor: "python:<name>"` SHALL be dispatched individually to their registered functions. The system SHALL NOT issue one LLM call per indicator.

#### Scenario: One LLM call per section for llm-extractor rules
- **WHEN** five `report`-type rules with `extractor: "llm"` resolve to the same section
- **THEN** exactly one `ai_extract` call is made for that section, returning five `{indicator, value, period, unit}` records.

#### Scenario: Python extractors run without LLM
- **WHEN** three `report`-type rules declare `python:*` extractors on the same section
- **THEN** the section text is fetched once and each rule's extractor function is called with that text; no `ai_extract` call is made for them.

#### Scenario: Mixed extractors on one section
- **WHEN** a section has both `llm` and `python:*` rules
- **THEN** the `python:*` rules are dispatched individually and the `llm` rules are covered by one batched `ai_extract` call for that section.

### Requirement: Compute derived ratios from extracted base values
For `computed`-type rules, the system SHALL evaluate their formulas locally using base values obtained from the `akshare` and `report` passes of the same call. The system SHALL NOT delegate arithmetic to the LLM. If any input is missing or non-numeric, the system SHALL place the indicator in `unresolved` with a note naming the missing input.

#### Scenario: Ratio computed from extracted bases
- **WHEN** `不良率` is `computed` from `不良贷款余额 / 贷款和垫款总额 * 100` and both bases were resolved
- **THEN** the system evaluates the formula locally and returns the ratio with `source_type: "computed"`, `extractor: "computed"`.

#### Scenario: Missing input lists as unresolved
- **WHEN** a computed rule's input was not found
- **THEN** the system adds the indicator to `unresolved` with `note: "missing input: <name>"` and `value: null`.

### Requirement: Cache the extracted indicator bundle on disk
The system SHALL persist the extracted indicator map for a stock/year as `{stem}.indicators.json` (alongside the existing cache artifacts), keyed by the applicable rule set. On a repeat `extract_indicators` call for the same company/year with the same applicable rule set, the system SHALL return the cached bundle without re-running extraction, unless the rule set has changed (detected by a `rules_hash` stored in the bundle).

#### Scenario: Repeat call is served from cache
- **WHEN** `extract_indicators` is called a second time for the same company/year with an unchanged rule set
- **THEN** the result is read from `{stem}.indicators.json`, no `ai_extract` or extractor call is made, and `cached` is `true`.

#### Scenario: Rule-set change busts the cache
- **WHEN** the `rules_hash` stored in the cached bundle differs from the current applicable rule set's hash
- **THEN** the system treats the bundle as missing and re-runs extraction, then writes a fresh bundle with the new hash.

#### Scenario: Cache eviction
- **WHEN** `clear_cache(stock_code, year)` is called
- **THEN** the `{stem}.indicators.json` file for that stock/year is removed along with the other cache artifacts.

### Requirement: Result shape and provenance
The system SHALL return `{stock_code, company_name, year, form, pdf_url, cached, indicators: {...}, missing: [...], unresolved: [...]}`. Each value entry SHALL carry `value`, `unit`, `source_type`, `extractor`, `source`, `period`, and `provenance`. The tool SHALL be wrapped in `@_tool_safe` so failures become `{"error": "..."}`.

#### Scenario: Full result shape on success
- **THEN** the returned object contains the company/year header fields, the `indicators` map, and both `missing` and `unresolved` arrays (empty when nothing is missing).

#### Scenario: No applicable indicators resolvable
- **WHEN** none of the requested indicators are applicable/resolvable for the company
- **THEN** the system returns the header fields with an empty `indicators` map and a populated `missing`/`unresolved` list, not an error.
