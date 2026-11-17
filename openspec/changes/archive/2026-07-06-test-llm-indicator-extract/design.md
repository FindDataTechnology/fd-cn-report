## Context

The LLM extraction path is the only indicator-extraction route with no tests. It is exercised end-to-end by `scripts/extract_indicators_by_position.py --extractor llm`, but in the test suite [test_cnreport.py](file:///Users/chengsishi/finddata/cnreport/test_cnreport.py) pops `LLM_API_KEY` so no LLM call is ever made. The path spans two modules:

- [`cnreport_tools.call_llm_json`](file:///Users/chengsishi/finddata/cnreport/cnreport_tools.py#L332) — OpenAI-compatible HTTP call with 429/connection-error retries, `response_format: json_object`.
- [`indicators_client._llm_extract_section`](file:///Users/chengsishi/finddata/cnreport/indicators_client.py#L440) — builds the system/user prompt, sends `wanted: [{indicator, unit, schema_hint...}]` + section text, parses `{records:[{indicator,value,period,unit}]}`.

Form applicability is gated by [`_form_compatible`](file:///Users/chengsishi/finddata/cnreport/indicators_client.py#L421) via `_FORM_COMPAT_KEY` (`年度报告→年报`, `半年度报告→半年报`, `第一季度报告→季报`, `第三季度报告→季报`). The four forms are the only periodic report types in [cninfo_categories.json](file:///Users/chengsishi/finddata/cnreport/cninfo_categories.json) under group `定期报告`.

Existing conventions:
- Tests live at repo root (`test_cnreport.py`); fixtures at `test_fixtures/`.
- Tests run with no network and no `LLM_API_KEY`.

## Goals / Non-Goals

**Goals:**
- Verify the LLM extraction contract (request shape, response schema, error/not-found fallbacks) without network.
- Verify the bundle produced by `extract_indicators_by_position(extractor="llm", form=...)` matches the shape the CLI script writes to `./out/*.json`.
- Make "the report types that exist" an executable check (the 4 forms + `_FORM_COMPAT_KEY` mapping + cninfo category codes).
- Cover all four forms in a parametrized test.

**Non-Goals:**
- Live LLM calls / OpenRouter rate-limit tuning — out of scope; covered manually via the script.
- Changing production extraction code. If a test reveals a bug, file a follow-up change.
- Testing the python extractors (regex_amount, headcount, etc.) — already pure functions; leave to existing test module.
- Cross-company regression data (ICBC/茅台) — fixtures use a minimal synthetic company, not a real PDF.

## Decisions

**Decision 1 — Mock `call_llm_json`, not HTTP.**
Mock `cnreport_tools.call_llm_json` (the function `_llm_extract_section` calls as `T.call_llm_json`). *Why:* the LLM path's contract is the JSON `{records:[...]}` payload, not the HTTP wire format. Mocking httpx would couple tests to retry internals and `response_format` headers. *Alternative considered:* recording real responses as VCR cassettes — rejected: brittle against model/output drift and requires a key.

**Decision 2 — Fixtures mirror the script bundle, not a hand-rolled shape.**
The fixture's expected bundle is authored to match the exact fields `scripts/extract_indicators_by_position.py` writes: `{stock_code, company_name, year, form, pdf_url, cached, indicators:{name:{value,unit,source_type,extractor,source,period,provenance}}, missing, unresolved, skipped, csv_path, extractor_mode}`. *Why:* the user explicitly wants "information filled like indicators extract from scripts". Matching the script output means a future diff between engine and script is caught. *Alternative:* assert only a subset of fields — rejected: misses field regressions.

**Decision 3 — Stub PDF + section text via the report cache, not a real fetch.**
Inject a canned report (text + outline) through the existing `report_cache` / `_build_ctx` indirection so no cninfo fetch happens. *Why:* reuses the engine's own cache seam instead of monkey-patching `fetch_pdf`. If the engine lacks a clean seam, fall back to monkey-patching the fetch function at module level (recorded as a task with an explicit fallback note).

**Decision 4 — Parametrize across the 4 forms; one synthetic company.**
One `pytest.mark.parametrize` over `["年度报告","半年度报告","第一季度报告","第三季度报告"]` with per-form expected `skipped` (form-incompatible rules) and `indicators` (form-compatible rules). *Why:* the form-compat gate is the riskiest part of the multi-form change; parametrization makes the "which report types exist" answer executable. *Alternative:* one test per form — rejected: duplicative.

**Decision 5 — Fixtures under `test_fixtures/llm_extract/`.**
`test_fixtures/llm_extract/section_<form>.txt` (canned section text) and `llm_response_<form>.json` (canned `{records:...}`). *Why:* matches existing `test_fixtures/` convention and keeps large text out of the test file.

## Risks / Trade-offs

- [Engine has no clean PDF-injection seam] → Mitigation: Decision 3 fallback (monkey-patch the fetch function); task explicitly verifies the seam first and records which path was taken.
- [Fixtures drift from real script output] → Mitigation: generate the fixture's expected bundle by running the real script once with `--extractor llm` against a synthetic stub, then freeze it; the design doc records this as the canonical source.
- [LLM mock hides real prompt regressions] → Mitigation: assert the mock received the expected `wanted` payload (indicator names + units) so prompt-shape changes fail the test.
- [Form-compat matrix in fixture gets stale vs `_FORM_COMPAT_KEY`] → Mitigation: a dedicated test reads `_FORM_COMPAT_KEY` and `cninfo_categories.json` directly, so the source of truth is code, not a hand-maintained table.
