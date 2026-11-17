## 1. Fixtures (canned inputs + expected bundle)

- [x] 1.1 Create `test_fixtures/llm_extract/section.txt` — a minimal synthetic report text (outline `第三节`/`第四节` headings + a `合并资产负债表` body) containing `资产总计` / `负债合计` / `所有者权益合计` figures. Renamed from `section_年度报告.txt` since the section text is form-agnostic (the body-text fallback resolves `balance_sheet` regardless of form).
- [x] 1.2 Create `test_fixtures/llm_extract/llm_response_ok.json` — `{"records":[{"indicator":"资产总计","value":1234567,"period":"annual","unit":"元"},{"indicator":"负债合计","value":456789,"period":"annual","unit":"元"},{"indicator":"营业收入","value":999000,"period":"annual","unit":"元"}]}`.
- [x] 1.3 Create `test_fixtures/llm_extract/llm_response_partial.json` — records omitting `负债合计` (covers the "not returned" fallback).
- [x] 1.4 Replaced the frozen `expected_bundle_*.json` file with **shape assertions** in `test_bundle_shape_per_form`. Rationale: a frozen bundle would need to match `rules_hash` (a sha1 of the sample rules), which is brittle and adds no real coverage over asserting the field set + specific canned values directly. The shape assertion still verifies the bundle mirrors what `scripts/extract_indicators_by_position.py` writes (header fields + `indicators`/`missing`/`unresolved`/`skipped`/`csv_path`/`extractor_mode`).
- [x] 1.5 Create `test_fixtures/llm_extract/rules.sample.json` with 3 report rules on `balance_sheet`: `资产总计` (`report_type:"年报/半年报/季报"`), `负债合计` (`report_type:"年报"`, annual-only), `营业收入` (no `report_type`, broadly applicable). Plus `test_fixtures/llm_extract/indicators_position.csv` naming the three indicators.

## 2. Test scaffolding

- [x] 2.1 Create `test_llm_indicator_extract.py` at repo root with the same env hygiene as `test_cnreport.py` (`sys.path` insert, pop `LLM_API_KEY`/`OPENAI_API_KEY`, `CNREPORT_CACHE_DIR` to a tmp dir).
- [x] 2.2 In-file fixtures load `test_fixtures/llm_extract/*` (rules, section text, LLM responses) as module-level constants.
- [x] 2.3 `report_cache` injection: the engine has no pre-populated cache seam, so `_stubbed_engine` monkey-patches `report_cache.get_or_fetch` to return canned text, `get_cached_indicators` → `None`, `write_cached_indicators` → no-op. Also patches `cninfo_client.lookup_company` / `query_announcements` so `_build_ctx` never hits the network. No `_PDF_INJECTION_MODE` constant needed — the stubbing is uniform.

## 3. Report-forms reference test ("the report types that exist")

- [x] 3.1 `test_form_compat_key_exhaustive` — asserts `_FORM_COMPAT_KEY` keys/values are exactly `{年度报告,半年度报告,第一季度报告,第三季度报告}` → `{年报,半年报,季报,季报}`.
- [x] 3.2 `test_forms_match_cninfo_categories` — asserts the `定期报告` group has the four form names + the expected `category_*_szsh` codes.
- [x] 3.3 `test_form_compatible_gate` parametrized over the 4 forms — asserts `资产总计`/`营业收入` compatible everywhere, `负债合计` compatible only for `年度报告`.

## 4. LLM extraction contract tests

- [x] 4.1 `test_llm_called_once_per_section_and_prompt_shape` — asserts one LLM call and `user` payload has `period` + `wanted` (len 3, each `indicator`+`unit`) + `text`. (Annual form → 3 rules.)
- [x] 4.2 `test_records_mapped_to_indicators` — asserts `indicators` has the canned values and `extractor:"llm"`.
- [x] 4.3 `test_indicator_not_returned_is_null` — partial response → `负债合计` `value:None`, note contains `not returned`.
- [x] 4.4 `test_llm_error_yields_nulls` — mock raises `RuntimeError` → every rule `value:None`, note starts with `llm error`.
- [x] 4.5 `test_no_api_key_yields_nulls_without_call` — `llm_config` patched to empty key → nulls + `LLM_API_KEY not configured`, `call_llm_json` never reached.

## 5. Parametrized bundle-shape test across all four forms

- [x] 5.1 `test_bundle_shape_per_form` parametrized over all 4 forms — header fields present, `form`/`extractor_mode` correct, each `indicators` entry carries the 7 fields, `skipped` entries are `{indicator,source_type,note}`.
- [x] 5.2 `test_annual_only_rule_skipped_and_not_in_wanted` parametrized over 半年报/Q1/Q3 — `负债合计` in `skipped` with `source_type:"form_filter"`, note `not in <form>`, and NOT in the captured `wanted` payload.
- [x] 5.3 `test_output_stem_rule` — imports `scripts/extract_indicators_by_position.py` via importlib, calls `_write_outputs`, asserts `000000_2023.json` (annual) and `000000_2023_半年度报告.json` (non-annual) are created.

## 6. No-network / no-key verification + full run

- [x] 6.1 `test_no_httpx_request_leaves_process` — patches `httpx.post` to raise; runs the full ok-path extraction; asserts it succeeds without `httpx.post` being called.
- [x] 6.2 `pytest test_llm_indicator_extract.py -v` → 20 passed (with `LLM_API_KEY`/`OPENAI_API_KEY` unset).
- [x] 6.3 Full `pytest` suite → 91 passed (71 existing + 20 new), no regressions.
