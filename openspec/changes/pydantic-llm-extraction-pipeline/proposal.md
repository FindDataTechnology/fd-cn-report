## Why

The current pipeline uses 6 different extractor types (`python:table_row`, `llm`, `python:percent_value`, `python:headcount`, `auto`, `computed`) scattered across 321 rules. The Python extractors (`python:table_row` — 186 rules) use fragile regex heuristics that return wrong values (e.g., row indices instead of actual figures) and have near-zero test coverage. LLM calls use freeform JSON prompting with no schema validation — the LLM can return malformed or missing fields silently. As the rule set grows, this extraction spaghetti becomes unmaintainable. A single, Pydantic-validated LLM extraction path eliminates regex fragility, guarantees structured output, and makes rule maintenance mechanical.

## What Changes

- **Remove** all `python:table_row`, `python:percent_value`, and `python:headcount` extractors from `indicator_rules.json` — replace with `llm` extractors grouped by report section.
- **Introduce** Pydantic models per report section (balance_sheet, income_statement, cashflow, report_section) that define the exact indicators to extract, their types, and validation.
- **Rewrite** the LLM extraction dispatch to use Pydantic models as the output schema, replacing freeform JSON prompting.
- **Add** a high-level orchestration script that downloads reports, resolves sections, runs parallel LLM extraction across sections/rules, and returns a pandas DataFrame.
- **BREAKING**: `extract_indicators` result shape changes from `{name: {value, note}}` dict to flat DataFrame; `extractor_mode` semantics change (no more `mock` — all extraction uses LLM).
- **BREAKING**: `indicator_rules.json` drops `extractor` field for report-type rules — extractor is inferred from rule's `module` + Pydantic model lookup.

## Capabilities

### New Capabilities
- `pydantic-extract`: Pydantic model definitions per report section + LLM extraction that validates output against the model.
- `pipeline-orchestrator`: High-level entry point that auto-downloads reports, resolves sections, dispatches parallel extraction, and returns a pandas DataFrame.
- `rule-admin`: CLI/GUI tools for adding, removing, and modifying rules with Pydantic-schema-aware validation.

### Modified Capabilities
- `indicator-batch-extract`: Extraction dispatch rewritten — one Pydantic model per section replaces per-indicator Python extractors; result shape changes to DataFrame.
- `indicator-rules`: `extractor` field removed for report-type rules; rules define only `module` + `selectors`; Pydantic model maps module to extractable fields.
- `llm-indicator-extract`: Pydantic model replaces freeform JSON prompt; one call per section produces strongly-typed batch of indicators.

## Impact

- **Code**: `indicators_client.py` — major rewrite of `_resolve_via_report`, `_run_extractor` removed; `cnreport_tools.py` — add Pydantic models, replace `call_llm_json` with typed `call_llm_pydantic`; `report_cache.py` — no change.
- **Dependencies**: Add `pydantic` (already in pyproject.toml as dev-dep, promote to runtime) and optionally `rich` for CLI table output.
- **Data**: `indicator_rules.json` — 186 rules lose `extractor: "python:table_row"` (simplified); orchestration script produces CSV/Parquet via pandas.
- **Tests**: Python extractor unit tests replaced by Pydantic model tests + LLM mock tests; integration tests verify extraction against known PDFs.
