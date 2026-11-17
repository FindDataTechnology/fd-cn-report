# pydantic-extract

## Purpose

Define Pydantic models per report section for LLM extraction validation, and provide a typed `call_llm_pydantic` function that uses OpenAI `json_schema` response format to produce strongly-typed extraction results from a single LLM call per section.

## ADDED Requirements

### Requirement: Per-section Pydantic model defines exactly which indicators to extract

The system SHALL define one Pydantic model per report module (balance_sheet, income_statement, cashflow, report_section). Each model SHALL inherit from a `BaseExtractionResult` base model carrying metadata fields `section: str`, `page: Optional[int]`, `source: str`. Each indicator field SHALL be `Optional[Decimal]` with `Field(None)` default. Field names SHALL match indicator rule names (Chinese). Each field SHALL carry a `Field(alias=...)` with a camelCase ASCII alias used as the JSON Schema key for LLM interaction.

#### Scenario: BalanceSheetResult model contains all balance sheet indicators

- **WHEN** the `BalanceSheetResult` model is inspected
- **THEN** it contains fields for every `balance_sheet` module indicator from `indicator_rules.json` (86 rules), each typed as `Optional[Decimal]`, with ASCII alias names.

#### Scenario: IncomeStatementResult model contains all income statement indicators

- **WHEN** `IncomeStatementResult` is inspected
- **THEN** it contains fields for every `income_statement` module indicator (41 rules).

#### Scenario: CashflowResult model contains all cash flow indicators

- **WHEN** `CashflowResult` is inspected
- **THEN** it contains fields for every `cashflow` module indicator (100 rules).

#### Scenario: ReportSectionResult model covers MD&A/risk/HR sections

- **WHEN** `ReportSectionResult` is inspected
- **THEN** it contains fields for every `report_section` module indicator (76 rules) as a flat model, with each field `Optional[Decimal]`.

### Requirement: Pydantic model generates a JSON Schema for LLM structured output

The system SHALL provide `model_to_json_schema(model: type[BaseModel]) -> dict` that converts a Pydantic model to a JSON Schema compatible with OpenAI's `response_format: {"type": "json_schema", "json_schema": {"name": "...", "schema": ...}}`. The schema SHALL use the field aliases as property names. Only non-None fields with aliases SHALL be included in the schema. The schema SHALL be generated at import time to avoid repeated work.

#### Scenario: Generated schema is accepted by OpenAI API

- **WHEN** `model_to_json_schema(BalanceSheetResult)` is called
- **THEN** the result is a valid JSON Schema dict with property names matching the ASCII aliases, and the schema is accepted by `response_format.json_schema` on an OpenAI-compatible endpoint.

### Requirement: `call_llm_pydantic` dispatches a typed LLM extraction call

The system SHALL provide `call_llm_pydantic(system, user, model_class) -> model_class` that:
1. Builds the JSON Schema from `model_class` via `model_to_json_schema`.
2. Submits the LLM call with `response_format: {"type": "json_schema", "json_schema": {"name": "...", "schema": ...}}`.
3. Parses the response through `model_class.model_validate(response_json)`.
4. Returns the validated Pydantic model instance.

#### Scenario: Valid LLM response is parsed into the model

- **WHEN** the LLM returns valid JSON matching the schema with all fields populated
- **THEN** `model_validate` succeeds and the returned model's field values are populated as `Decimal`.

#### Scenario: Partial response populates only returned fields

- **WHEN** the LLM returns JSON with a subset of fields
- **THEN** populated fields are set, missing fields remain `None` in the model.

#### Scenario: Null fields in response are set to None

- **WHEN** the LLM returns a field with `null`
- **THEN** the model field is `None`.

#### Scenario: Non-numeric value returned for a Decimal field

- **WHEN** the LLM returns a string for a `Decimal` field
- **THEN** `model_validate` raises `ValidationError`, triggering a retry (see retry requirement).

### Requirement: `call_llm_pydantic` falls back gracefully when `json_schema` is unsupported

When the LLM provider returns a 400 error for `json_schema` response format, the system SHALL retry once with `response_format: {"type": "json_object"}` and parse the response through `model_class.model_validate`. If the provider also rejects `json_object`, the system SHALL retry once with no `response_format` and attempt `model_validate` on the raw response. If all fallbacks fail, the system SHALL raise `RuntimeError`.

#### Scenario: json_schema rejected, json_object succeeds

- **WHEN** the provider returns 400 for `json_schema` and the retry with `json_object` succeeds
- **THEN** the response is parsed through `model_validate` and the model is returned; the function does not raise.

### Requirement: Missing or invalid indicators are recorded, not propagated

If an indicator field name from the rule set has no corresponding field in the Pydantic model, the system SHALL log a warning and skip that indicator during extraction. If the LLM returns a value outside the field's validation constraints (e.g., negative for `Field(ge=0)`), the system SHALL record `None` for that field with a note "validation constraint breached: <field_name>".

#### Scenario: Unknown indicator name in rules is skipped

- **WHEN** `indicator_rules.json` contains a rule named `no_such_field` and no Pydantic model has a matching field
- **THEN** the extraction run logs "skipping unknown indicator: no_such_field" and does not include it in the LLM prompt.

### Requirement: Tests run with mocked LLM responses

The test suite for `call_llm_pydantic` SHALL mock the underlying HTTP call and inject canned JSON responses. Tests SHALL verify `model_validate` behavior for valid, partial, null, and invalid responses. Tests SHALL verify fallback behavior. The suite SHALL NOT require `LLM_API_KEY`.

#### Scenario: All modeled test cases pass with no API key

- **WHEN** the test module runs with `LLM_API_KEY` and `OPENAI_API_KEY` unset
- **THEN** every test passes and no HTTP request leaves the process.
