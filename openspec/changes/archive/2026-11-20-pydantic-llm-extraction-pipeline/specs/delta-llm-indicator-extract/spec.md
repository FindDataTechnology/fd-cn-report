# llm-indicator-extract (Delta)

## MODIFIED Requirements

### Requirement: LLM extraction is one call per section with a Pydantic model

For a set of `report`-type rules assigned to one section, the extractor SHALL make a single LLM call. The call SHALL use the section's Pydantic model as the response schema via `response_format.json_schema`. The system prompt SHALL instruct the LLM to return a JSON object matching the schema's field names. The user payload SHALL contain `period`, the section `text`, and the list of wanted indicators with their full Chinese names and expected units. The response SHALL be validated through `model_validate` on the Pydantic model.

#### Scenario: LLM receives the expected prompt shape with structured output

- **WHEN** the LLM extractor runs for a section with two report rules
- **THEN** the mocked `call_llm_pydantic` is invoked exactly once for that section, its `user` argument parses as JSON containing `period` and `text`, and the `response_format` includes `json_schema` with the section's schema.

#### Scenario: Records are mapped back to rule names via model fields

- **WHEN** the LLM returns valid JSON matching the Pydantic model and `model_validate` succeeds
- **THEN** each non-None field in the model maps to an indicator in the results with `value` set to the field's `Decimal` converted to `float` and `extractor: "llm"`.

### Requirement: Missing indicators and errors resolve to null value

When an indicator field is `None` in the validated Pydantic model (the LLM omitted it or returned `null`), the extractor SHALL record it with `value: null` and a note indicating it was not returned. When the LLM call raises (network, parse, or missing-API-key), the extractor SHALL NOT propagate the exception; it SHALL record every indicator in that section with `value: null` and a note describing the failure class.

#### Scenario: Indicator not returned by the LLM (field is None)

- **WHEN** the LLM returns a response where a field is `null`
- **THEN** `model_validate` sets that field to `None`, and the indicator appears with `value: null` and a note containing "not returned".

#### Scenario: LLM call fails

- **WHEN** the mocked `call_llm_pydantic` raises `RuntimeError`
- **THEN** every indicator in the section appears with `value: null` and a note starting with `llm error`.

#### Scenario: API key not configured

- **WHEN** `LLM_API_KEY` is unset and the extractor runs
- **THEN** every indicator in the section appears with `value: null` and note `LLM_API_KEY not configured`, and no HTTP call is attempted.

### Requirement: Form-incompatible rules are skipped, not extracted

Rules whose `report_type` does not include the requested form's compat key SHALL be placed in the `skipped` list with `source_type: "form_filter"` and note `not in <form>`, and SHALL NOT be sent to the LLM. Rules with no `report_type` SHALL be treated as compatible with every form. *(Unchanged from original spec.)*

#### Scenario: Annual-only rule is skipped for Q1

- **WHEN** extraction runs with `form="第一季度报告"` and a rule declares `report_type: "年报"`
- **THEN** that rule appears in `skipped` with `source_type: "form_filter"` and is not present in the `indicators` map and not in the `wanted` payload sent to the LLM. *(Unchanged from original spec.)*

### Requirement: Result bundle mirrors the position-extraction script output

`extract_indicators_by_position(..., extractor="llm", form=<form>)` SHALL return a bundle with the header fields `{stock_code, company_name, year, form, pdf_url, cached, csv_path, extractor_mode}` and the lists `indicators`, `missing`, `unresolved`, `skipped`. Each `indicators` entry SHALL carry `{value, unit, source_type, extractor, source, period, provenance}`. *(Unchanged from original spec — the bundle shape is preserved for backward compatibility. The new `extract_to_dataframe` is the primary output path; the old bundle remains as a legacy format.)*

### Requirement: Tests run without network or API key

The LLM-extraction test suite SHALL make zero network calls and SHALL NOT require `LLM_API_KEY` or `OPENAI_API_KEY`. The suite SHALL mock `cnreport_tools.call_llm_pydantic` and inject canned Pydantic model instances. *(Updated: mocks `call_llm_pydantic` instead of `call_llm_json`, injects model instances not raw dicts.)*

#### Scenario: Suite passes with no env and no network

- **WHEN** the new test module runs in an environment with `LLM_API_KEY` and `OPENAI_API_KEY` unset and no network access
- **THEN** every test passes and no `httpx` request leaves the process.
