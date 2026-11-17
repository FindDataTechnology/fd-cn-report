# llm-indicator-extract Specification

## Purpose
TBD - created by syncing change test-llm-indicator-extract. Update Purpose after archive.

## Requirements

### Requirement: Supported report forms
The LLM indicator extractor SHALL support the four CN periodic report forms (`年度报告`, `半年度报告`, `第一季度报告`, `第三季度报告`) AND the offering/HK report forms (`招股说明书`, `港股全球发售`, `港股年度报告`). The supported form set SHALL be extensible: adding a form requires only a `_FORM_COMPAT_KEY` entry (in both `indicators_client` and `report_section_map`) and a matching `document_type` on its rules. Each form SHALL map to a compatibility key via `_FORM_COMPAT_KEY` used to gate rule applicability. The four periodic forms SHALL correspond to the four categories under the `定期报告` group in `cninfo_categories.json`; `招股说明书` SHALL correspond to the `首发` category (`category_sf_szsh`) under the `融资` group.

#### Scenario: All supported forms are accepted by the extraction entry points
- **WHEN** `extract_indicators_by_position(ticker_or_name=<synthetic>, year=<year>, extractor="llm", form=<form>)` is called for each of the seven supported forms
- **THEN** the call does not raise `KeyError`/`ValueError` for any form, and the returned bundle's `form` field equals the requested form.

#### Scenario: Form-compat key mapping covers all supported forms
- **WHEN** the test reads `_FORM_COMPAT_KEY` from `indicators_client`
- **THEN** its keys include the four periodic forms plus `招股说明书`, `港股全球发售`, `港股年度报告`, and each maps to its compat key.

#### Scenario: CN forms match cninfo categories
- **WHEN** the test reads `cninfo_categories.json`
- **THEN** the `定期报告` group's category names are the four periodic forms, and the `融资` group contains `首发` mapped to `招股说明书`.

### Requirement: LLM system prompt is period-parameterized and report-type-agnostic
The `_llm_extract_section` system prompt SHALL be parameterized by the requested period (year/period) and SHALL NOT contain a hard-coded year. The prompt SHALL NOT assume the source document is a CN annual report; it SHALL describe the target period explicitly and apply to prospectus and HK report text as well as CN periodic reports.

#### Scenario: Prompt uses the requested period, not a hard-coded year
- **WHEN** the LLM extractor runs with `year=2024` for any supported form
- **THEN** the system prompt passed to `call_llm_json`/`call_llm_pydantic` references `2024` and does not contain the literal `2023`.

#### Scenario: Prompt does not assert an annual report
- **WHEN** the LLM extractor runs with `form="招股说明书"`
- **THEN** the system prompt does not assert the document is an annual report (no `年报`/`annual-report` document-type assertion).

### Requirement: LLM extraction is one call per section per module with a JSON records schema
For a set of `report`-type rules assigned to one section, the extractor SHALL make one LLM call per `(module, subgroup)` group — **or reuse the records already cached for that group by the section cache** (`llm_section_cache`). The call SHALL be issued through `call_llm_pydantic` with the subgroup's Pydantic model (`indicators_models.model_for_subgroup`) as the response schema, and SHALL send a system instruction built by `_build_llm_system_prompt` plus a user payload containing `period`, a field description per **missing** indicator, and the section `text`. Every `report`-type rule in a resolved section SHALL be included in the LLM call — there is no longer a split between `llm_rules` and `python_rules` within a section. A group whose indicators are already fully present in the cache SHALL NOT trigger an LLM call. The `extractor_mode: "python"` argument SHALL place all report rules in `unresolved` with note `skipped: llm extractor in python mode` (since no Python extractors exist).

The section cache is keyed by `(pdf_url, section_key, period, rules_hash)`, where `rules_hash` is the stable hash over **all** rules in that `(module, subgroup)` (`_subgroup_rules_hash`). The wanted set is deliberately **not** part of the key: the cache stores the union of records ever fetched for the group, and the caller derives the missing subset locally. A change in section text (`pdf_url`/`section_key`/`period`) or in the rule set therefore produces a fresh LLM call; a change in the requested subset alone does not.

#### Scenario: LLM receives the expected prompt shape
- **WHEN** the LLM extractor runs for a section with two report rules and no section-cache hit
- **THEN** `call_llm_pydantic` is invoked exactly once for that group, its `user` argument parses as JSON containing `period`, the field descriptions for both indicators, and `text`.

#### Scenario: Records are mapped back to rule names
- **WHEN** the LLM returns an instance whose `model_dump()` holds the two indicator names
- **THEN** the bundle's `indicators` map contains those two names with the returned values and `extractor: "llm"`, and the records are persisted to the section cache (metadata fields `section`/`page`/`source` excluded).

#### Scenario: Full cache hit avoids a second LLM call
- **WHEN** a previous run cached records for `(pdf_url, section_key, period, rules_hash)` and the current run requests the same group with the same rules hash
- **THEN** `call_llm_pydantic` is not invoked, the cached values are returned with note `llm-section-cache`, and `section_cache_reuse` counts them.

#### Scenario: Partial hit queries only the missing indicators
- **WHEN** the section cache holds records for `{A, B}` and the current run requests `{A, B, C}`
- **THEN** `call_llm_pydantic` is invoked once with a model containing only `C`, `A` and `B` are served from the cache, and `put()` merges `C` into the stored superset so the entry grows to `{A, B, C}`.

#### Scenario: Rules-hash change invalidates the cache
- **WHEN** `indicator_rules.json` is edited so `_subgroup_rules_hash` returns a new value
- **THEN** the next run does not reuse the entries written under the previous hash and makes a fresh LLM call.

#### Scenario: All report rules in a section go to LLM
- **WHEN** a section contains 5 `balance_sheet` rules and 3 `report_section` rules
- **THEN** the system makes 2 LLM calls (one per module), each including all rules of that module as fields in the Pydantic schema.

#### Scenario: Python mode skips all report rules
- **WHEN** `extractor_mode="python"` is passed and a `report` rule has `extractor: "llm"`
- **THEN** that rule is listed in `unresolved` with note `skipped: llm extractor in python mode` and no LLM call is made.

### Requirement: Missing indicators and errors resolve to null value
When an indicator is absent from the LLM response, the extractor SHALL record it with `value: null` and a note indicating it was not returned. When the LLM call raises (network, parse, or missing-API-key), the extractor SHALL NOT propagate the exception; it SHALL record every rule in that section with `value: null` and a note describing the failure class.

#### Scenario: Indicator not returned by the LLM
- **WHEN** the LLM returns records that omit a requested indicator
- **THEN** that indicator appears in `indicators` with `value: null` and a note containing "not returned".

#### Scenario: LLM call fails
- **WHEN** the mocked `call_llm_json` raises `RuntimeError`
- **THEN** every rule in the section appears in `indicators` with `value: null` and a note starting with `llm error`.

#### Scenario: API key not configured
- **WHEN** `LLM_API_KEY` is unset and the extractor runs
- **THEN** every rule in the section appears with `value: null` and note `LLM_API_KEY not configured`, and no HTTP call is attempted.

### Requirement: Form-incompatible rules are skipped, not extracted
Rules whose `report_type` does not include the requested form's compat key SHALL be placed in the `skipped` list with `source_type: "form_filter"` and note `not in <form>`, and SHALL NOT be sent to the LLM. Rules with no `report_type` SHALL be treated as compatible with every form. This filtering SHALL apply in every extraction entry point - both `extract_indicators` and `extract_indicators_by_position` - not only the CSV-driven path.

#### Scenario: Annual-only rule is skipped for Q1
- **WHEN** extraction runs with `form="第一季度报告"` and a rule declares `report_type: "年报"`
- **THEN** that rule appears in `skipped` with `source_type: "form_filter"` and is not present in the `indicators` map and not in the `wanted` payload sent to the LLM.

#### Scenario: Rule without report_type is extracted for every form
- **WHEN** a rule has no `report_type` field and extraction runs for each supported form
- **THEN** the rule is delegated to the engine (not in `skipped`) for every form.

#### Scenario: Prospectus rule is skipped for an annual form in the plain path
- **WHEN** `extract_indicators` (plain, non-CSV path) runs with `form="年度报告"` and a rule declares `report_type: "招股说明书"`
- **THEN** that rule appears in `skipped` with `source_type: "form_filter"`.

### Requirement: Result bundle mirrors the position-extraction script output
`extract_indicators_by_position(..., extractor="llm", form=<form>)` SHALL return a bundle with the header fields `{stock_code, company_name, year, form, pdf_url, cached, csv_path, extractor_mode, section_cache_reuse}` and the lists `indicators`, `missing`, `unresolved`, `skipped`. Each `indicators` entry SHALL carry `{value, unit, source_type, extractor, source, period, provenance}`. The `skipped` array SHALL contain `{indicator, source_type, note}` entries. The `section_cache_reuse` field SHALL be an integer count of indicator records served from the section cache (zero when no section cache hit occurred); it is independent of `cached`, which indicates a full bundle hit.

#### Scenario: Bundle shape on a successful LLM extraction
- **WHEN** extraction runs with the LLM mocked to return valid records
- **THEN** the returned bundle contains every header field, every `indicators` entry carries the seven fields, `extractor_mode` equals the requested mode, and `section_cache_reuse` is an integer.

#### Scenario: Form is appended to the output stem for non-annual forms
- **WHEN** the script writes outputs for `form="半年度报告"`
- **THEN** the output stem is `<stock>_<year>_半年度报告` (not `<stock>_<year>`), matching the CLI's stem rule.

#### Scenario: section_cache_reuse reflects cached records
- **WHEN** a run reuses N indicator records from the section cache
- **THEN** `bundle["section_cache_reuse"]` equals N.

### Requirement: Tests run without network or API key
The LLM-extraction test suite SHALL make zero network calls and SHALL NOT require `LLM_API_KEY` or `OPENAI_API_KEY`. The suite SHALL mock `cnreport_tools.call_llm_json` and inject canned report text via the report-cache seam (or a documented fetch-function patch), consistent with the existing no-network contract in `test_cnreport.py`.

#### Scenario: Suite passes with no env and no network
- **WHEN** the new test module runs in an environment with `LLM_API_KEY` and `OPENAI_API_KEY` unset and no network access
- **THEN** every test passes and no `httpx` request leaves the process.

### Requirement: LLM extraction prioritizes section-resolved context over broad fallbacks
For `report`-type rules, the system SHALL prioritize using the text of the resolved section(s) as the LLM input context. If a selector expands to multiple candidate section titles via the section map, the engine SHALL select the first matching section in candidate order and SHALL NOT concatenate unrelated sections by default.

#### Scenario: First matching candidate is used
- **WHEN** a selector expands to candidates `[A, B, C]` and the outline contains both `B` and `C`
- **THEN** the engine uses `B` and records that matched title in provenance.

### Requirement: LLM requested indicator list is form-filtered and auditable
When building a single-section LLM request, the system SHALL ensure the `wanted` list excludes form-incompatible rules (per `report_type` gating) and SHALL record the final `wanted` indicator names in provenance for audit/debugging.

#### Scenario: Annual-only indicators are not sent for quarterly extraction
- **WHEN** extraction runs for `form="第一季度报告"` and a rule declares `report_type: "年报"`
- **THEN** that rule is excluded from the LLM request payload and appears in `skipped` with `source_type: "form_filter"`.
