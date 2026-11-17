## REMOVED Requirements

### Requirement: Supported periodic report forms
**Reason:** The supported form set is no longer limited to the four CN periodic forms; offering and HK report types (`招股说明书`, `港股全球发售`, `港股年度报告`) are now first-class forms. Replaced by "Supported report forms".
**Migration:** Callers passing the four periodic forms are unaffected. New callers may pass the offering/HK forms. Tests asserting "exactly four forms" must be updated to the extensible set.

## ADDED Requirements

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

## MODIFIED Requirements

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
