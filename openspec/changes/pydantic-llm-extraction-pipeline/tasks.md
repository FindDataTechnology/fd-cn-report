## 1. Pydantic Model Definitions

- [ ] 1.1 Create `indicators_models.py` with `BaseExtractionResult` base class (section, page, source metadata fields)
- [ ] 1.2 Define `BalanceSheetResult` model — all ~86 balance_sheet indicators as `Optional[Decimal]` with ASCII camelCase aliases
- [ ] 1.3 Define `IncomeStatementResult` model — all ~41 income_statement indicators with aliases
- [ ] 1.4 Define `CashflowResult` model — all ~100 cashflow indicators with aliases
- [ ] 1.5 Define `ReportSectionResult` model — all ~76 report_section indicators with aliases
- [ ] 1.6 Implement `model_to_json_schema()` — Pydantic model → JSON Schema dict with alias property names
- [ ] 1.7 Build `MODEL_REGISTRY: dict[str, type[BaseExtractionResult]]` mapping module → model + `model_for_module()` lookup

## 2. Typed LLM Extraction

- [ ] 2.1 Implement `call_llm_pydantic(system, user, model_class)` — uses `response_format.json_schema` with model's JSON Schema, parses via `model_validate`
- [ ] 2.2 Add `json_schema` → `json_object` → no-format fallback chain when provider rejects structured output
- [ ] 2.3 Add per-field validation constraints (`Field(ge=0, le=1e15)`) with rejection on constraint breach → `None` + note
- [ ] 2.4 Integrate field-level `min`/`max` from indicator_rules.json (if `value_range` exists) as additional Pydantic `Field` constraints

## 3. Extraction Pipeline Rewrite

- [ ] 3.1 Rewrite `_resolve_via_report` in `indicators_client.py` — call `call_llm_pydantic` with section's model instead of `_run_extractor`
- [ ] 3.2 Remove `_run_extractor()` and `python:` dispatch path from `indicators_client.py`
- [ ] 3.3 Add Pydantic model version hash to indicator cache key (busts cache when model fields change)
- [ ] 3.4 Add `dataframe: list[dict]` array to `extract_indicators` result bundle
- [ ] 3.5 Remove form-incompatible rule skipping path (already handled by existing `applicable_rules`)

## 4. Rule & Code Cleanup

- [ ] 4.1 Write migration script to drop `extractor` field from all report-type rules in `indicator_rules.json`
- [ ] 4.2 Delete `indicators_extractors.py` — all Python extractors are removed
- [ ] 4.3 Remove `python:table_row`, `python:percent_value`, `python:headcount` extractor code paths
- [ ] 4.4 Remove `register()` API and extractor registry references from docs
- [ ] 4.5 Run migration and verify `indicator_rules.json` has no `extractor` field on report-type rules

## 5. Pipeline Orchestrator

- [ ] 5.1 Implement `extract_to_dataframe(tickers, years, rules=None, concurrency=4) -> pd.DataFrame`
- [ ] 5.2 Add parallel PDF download across ticker-year pairs with progress indicator
- [ ] 5.3 Add concurrent Pydantic-typed LLM extraction across sections and ticker-years
- [ ] 5.4 Add CSV (UTF-8 BOM) and Parquet (Snappy) output options
- [ ] 5.5 Add per-ticker-year error isolation — one failure doesn't block others
- [ ] 5.6 Register `extract_to_dataframe` as a CLI entry point in `pyproject.toml`

## 6. Rule Admin CLI

- [ ] 6.1 Implement `extract_rules list [--module]` — tabular rule listing
- [ ] 6.2 Implement `extract_rules add <name> --module --selectors [--company]` — add with Pydantic model validation
- [ ] 6.3 Implement `extract_rules rm <name>` — remove rule
- [ ] 6.4 Implement `extract_rules edit <name> --field --value` — edit with validation
- [ ] 6.5 Implement `extract_rules json-schema --module` — preview JSON Schema for a module
- [ ] 6.6 Implement `extract_rules stats` — rule count summary
- [ ] 6.7 Register `extract_rules` as a CLI entry point in `pyproject.toml`

## 7. Testing & Verification

- [ ] 7.1 Write unit tests for Pydantic model `model_validate` — valid, partial, null, invalid responses
- [ ] 7.2 Write unit tests for `call_llm_pydantic` — mock HTTP, test fallback chain
- [ ] 7.3 Write unit tests for `model_to_json_schema` — verify alias property names, field types
- [ ] 7.4 Write integration test for `extract_to_dataframe` — cached PDF + mocked LLM
- [ ] 7.5 Write integration tests for `extract_rules` — add, rm, edit, list, stats
- [ ] 7.6 Run full regression: extract 平安银行 2025 + 工商银行 2023, compare found/missing against old baseline
- [ ] 7.7 Verify all tests pass with `LLM_API_KEY` unset and no network access
