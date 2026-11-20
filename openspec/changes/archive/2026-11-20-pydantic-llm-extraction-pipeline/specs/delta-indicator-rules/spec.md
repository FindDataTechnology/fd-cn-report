# indicator-rules (Delta)

## MODIFIED Requirements

### Requirement: Rule structure for report-type rules drops the `extractor` field

For `report`-type rules, the system SHALL NOT require an `extractor` field. The extractor SHALL be inferred from the rule's `module`: rules with known Pydantic model modules (balance_sheet, income_statement, cashflow, report_section) SHALL use LLM extraction via that model. Rules whose module has no corresponding Pydantic model SHALL produce `value: null` with note "no Pydantic model for module: <module>". The `selectors[]` chain, `applies_to`, `module`, `subgroup`, and `report_type` fields remain unchanged.

#### Scenario: report rule without extractor field is valid

- **WHEN** a `report`-type rule has `module: "balance_sheet"` and no `extractor` field
- **THEN** the rule is valid and its extraction is dispatched through `BalanceSheetResult` Pydantic model.

#### Scenario: Unknown module produces null

- **WHEN** a `report`-type rule has `module: "unknown_module"` and no Pydantic model exists
- **THEN** the indicator is recorded with `value: null` and note "no Pydantic model for module: unknown_module".

## REMOVED Requirements

### Requirement: Pluggable extractors dispatch by name

**Reason**: The pluggable Python extractor registry (54 lines in `indicators_extractors.py`) is replaced by Pydantic-typed LLM extraction. There are no more `python:table_row`, `python:percent_value`, or `python:headcount` extractors. All report-type extraction goes through per-section Pydantic models.

**Migration**: The `indicators_extractors.py` file is deleted. The `register()` API and `extractor: "python:<name>"` dispatch path in `_run_extractor` are removed. The `_resolve_via_report` function calls `call_llm_pydantic` with the section's model directly.

### Requirement: python extractor dispatch

**Reason**: Same as above — no Python extractors remain. The `_run_extractor` function is removed from `indicators_client.py`.

### Requirement: Registering a new extractor

**Reason**: Adding a new indicator requires adding a field to the relevant Pydantic model, not registering a Python function. The `register()` API is deleted.

## ADDED Requirements

### Requirement: Rule set is maintainable by editing Pydantic models

The primary way to add or remove an indicator SHALL be editing the relevant Pydantic model in `indicators_models.py`. Adding a field to `BalanceSheetResult` SHALL automatically make it available for LLM extraction in all balance sheet sections. Removing a field SHALL make it unavailable. The `indicator_rules.json` SHALL remain as the applicability and selector configuration layer, with Pydantic models as the extractable-indicator inventory.

#### Scenario: Adding a field to a model makes it extractable

- **WHEN** `class BalanceSheetResult(BaseExtractionResult):` gains a new field `应收利息: Optional[Decimal] = None`
- **THEN** the next `extract_indicators` call for a bank with a balance sheet rule named `应收利息` in `indicator_rules.json` SHALL include that field in the LLM prompt and extract its value.

#### Scenario: Removing a field skips extraction

- **WHEN** a field is removed from a Pydantic model
- **THEN** `extract_indicators` SHALL produce `value: null` with note "indicator not in Pydantic model" for any rule whose name matches the removed field.

### Requirement: `indicators_models.py` centralizes all Pydantic model definitions

A new file `indicators_models.py` SHALL contain:
1. `BaseExtractionResult` base class with `section`, `page`, `source`.
2. Per-module models (`BalanceSheetResult`, `IncomeStatementResult`, `CashflowResult`, `ReportSectionResult`).
3. `MODEL_REGISTRY: dict[str, type[BaseExtractionResult]]` mapping module name to model class.
4. `model_for_module(module: str) -> Optional[type[BaseExtractionResult]]` lookup function.
5. `model_to_json_schema(model) -> dict` helper.

The file SHALL NOT depend on `indicators_client.py` or `cnreport_tools.py` beyond `pydantic` and `decimal`.

#### Scenario: MODEL_REGISTRY covers all modules

- **WHEN** `MODEL_REGISTRY` is inspected
- **THEN** its keys are exactly `{"balance_sheet", "income_statement", "cashflow", "report_section"}`.
