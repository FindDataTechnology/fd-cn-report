## Why

The LLM indicator-extraction path ([`_llm_extract_section`](file:///Users/chengsishi/finddata/cnreport/indicators_client.py#L440) + [`call_llm_json`](file:///Users/chengsishi/finddata/cnreport/cnreport_tools.py#L332)) has no test coverage. The existing [test_cnreport.py](file:///Users/chengsishi/finddata/cnreport/test_cnreport.py) explicitly pops `LLM_API_KEY` and only exercises pure logic, so the LLM contract — one call per section, the `{records:[...]}` JSON schema, the per-form applicability gate, and the bundle shape that `scripts/extract_indicators_by_position.py` emits — is unverified. We also have no single place that enumerates which periodic report forms the extractor supports. This change adds a test suite plus fixtures that mirror the script's bundle, exercising the LLM path across all supported report types so regressions surface before they hit the script.

## What Changes

- Add a new `llm-indicator-extract` capability spec formalizing: the four supported periodic report forms (`年度报告` / `半年度报告` / `第一季度报告` / `第三季度报告`), the form-compatibility gate via `_form_compatible`, the one-LLM-call-per-section contract, the `{records:[{indicator,value,period,unit}]}` response schema, and the error → `{value:null}` fallback.
- Add a test module `test_llm_indicator_extract.py` (repo root, matching `test_cnreport.py`) that drives `extract_indicators_by_position(..., extractor="llm", form=<each form>)` with `call_llm_json` mocked, asserting the bundle matches the shape produced by `scripts/extract_indicators_by_position.py` (header fields + `indicators` / `missing` / `unresolved` / `skipped` / `csv_path` / `extractor_mode`).
- Add fixtures (canned section text + canned LLM JSON responses) under `test_fixtures/` (matching the existing fixture dir) that mirror what the script writes to `./out/*.json`, so the "information filled" matches a real extraction run.
- Add a report-forms reference test that asserts the four forms and their `_FORM_COMPAT_KEY` mapping, documenting "the report types that exist" as an executable check.

## Capabilities

### New Capabilities
- `llm-indicator-extract`: Formalizes the LLM-based indicator extraction contract — supported periodic report forms, form-compatibility gating, the one-call-per-section LLM request/response schema, error fallback, and the result bundle shape that mirrors the position-extraction script. Verified by a mocked test suite across all four forms.

### Modified Capabilities
<!-- None. The extractor-mode override and form-filter behavior already live in `indicator-position-extract`; this change adds a focused spec + tests for the LLM path itself, without altering existing requirements. -->

## Impact

- **New code**: a test module (e.g. `test_llm_indicator_extract.py`) and fixtures under `tests/test_fixtures/`.
- **Existing code**: no production-code changes expected. If a test surfaces a real bug, it is tracked as a follow-up task rather than folded into this change.
- **Dependencies**: uses existing `pytest`, `unittest.mock`. No new runtime deps. The OpenRouter/`LLM_*` env contract is exercised via mocks (no live network in CI).
- **CI**: the new tests must run without `LLM_API_KEY`, consistent with the existing test module's no-network contract.
