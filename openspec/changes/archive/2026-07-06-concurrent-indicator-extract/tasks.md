## 1. Concurrency primitives

- [x] 1.1 Add a `_resolve_concurrency(concurrency: int | None) -> int` helper in `indicators_client.py` that returns `concurrency` when given a positive int, else `int(os.environ.get("EXTRACT_CONCURRENCY", "4"))`, clamped to `>= 1`.
- [x] 1.2 Add a `_map_merge(items, fn, concurrency, *, label)` helper that: returns `[]` inline-mapped in order when `concurrency <= 1` or `len(items) <= 1` (no pool, deterministic order); otherwise maps `fn` over `items` with a `ThreadPoolExecutor(max_workers=concurrency)` and collects results in input order. Workers return plain values; the main thread does all `results` dict mutation.
- [x] 1.3 Verify (manual + assertion in tests) that `_RULES_CACHE`, `call_llm_json`, `report_cache`, `llm_section_cache`, and `financials_client.get_statements` have no module-level mutable state written from workers (read the modules; document the finding in a code comment near `_map_merge`).

## 2. Concurrent dispatch in `extract_indicators`

- [x] 2.1 Wrap each section's work (lines ~1042–1068) in a closure `_extract_one_section(sec)` that captures `rules_in_sec`, `section_text_cache[sec]`, `ctx`, and returns `(sec, {indicator_name: value_obj}, section_cache_reuse_delta)`. The closure calls `_llm_extract_section(...)` (LLM rules) and `_run_extractor(...)` (python rules) exactly as today.
- [x] 2.2 Replace the `for sec in sections:` loop with `_map_merge(sorted(set(section_of.values())), _extract_one_section, concurrency)`; merge each returned sub-result into `results` in the main thread; accumulate `section_cache_reuse` from each sub-result.
- [x] 2.3 Replace the `for r in akshare_rules:` loop (lines ~995–996) with `_map_merge(akshare_rules, lambda r: (r["name"], _resolve_via_akshare(...)), concurrency)`; merge into `results` in the main thread.
- [x] 2.4 Add `concurrency: int | None = None` parameter to `extract_indicators`; resolve it via `_resolve_concurrency` at the top of the function.
- [x] 2.5 Set `bundle["concurrency"] = <resolved cap>` in the returned bundle (both the fresh-extraction path and the no-PDF header path in `extract_indicators_by_position`).
- [x] 2.6 Keep the `extractor_mode == "python"` branch sequential (CPU-bound, fast) — confirm via test that no thread pool is used there (or that results are unaffected).
- [x] 2.7 Confirm the bundle-cache fast-path (`cached: true`) returns before any pool work and carries the `concurrency` field from the cached copy (add the field if missing on freshly cached bundles; tolerate its absence on pre-existing caches).

## 3. Propagate concurrency through the position entry point

- [x] 3.1 Add `concurrency: int | None = None` to `extract_indicators_by_position`; forward it to the inner `extract_indicators(...)` call.
- [x] 3.2 Propagate `concurrency` from the inner bundle to the outer bundle returned by `extract_indicators_by_position`.

## 4. `extract_indicators_batch` function

- [x] 4.1 Implement `extract_indicators_batch(targets, *, concurrency=None, csv_path="docs/indicators_position.csv", indicators=None, form="年度报告", extractor="auto")` where each target is a `(ticker, year)` or `(ticker, year, form)` tuple/dict.
- [x] 4.2 Inside, use `_map_merge(targets, _extract_one_target, batch_concurrency)` where `_extract_one_target` calls `extract_indicators_by_position` (or `extract_indicators` when no `csv_path`/position semantics are needed — decide per Open Question in design; default to the position path to match the scripts).
- [x] 4.3 Catch exceptions and `{"error": ...}` bundles per target; collect them into a `failures: list[{target, error}]` list; never let one target abort the batch.
- [x] 4.4 Return `{"results": {target_key: bundle}, "failures": failures}` (or `{target_key: bundle}` + `failures` — confirm shape against the spec; the keyed map SHALL be order-independent).
- [x] 4.5 Resolve the batch cap via a `concurrency` param falling back to an env var (default `2`); document in the docstring that peak in-flight LLM calls is bounded by `batch_concurrency × extract_concurrency`.

## 5. Wire the batch function into the scripts

- [x] 5.1 In `scripts/extract_indicators_by_position.py`, add a `--concurrency` CLI flag (default `None` → env/`4` for in-call, separate `--batch-concurrency` default `2` for the `--from-file` loop). When `--from-file` is used, delegate the per-target loop to `extract_indicators_batch` instead of the sequential `for target in _companies(args)`.
- [x] 5.2 In `scripts/extract_indicators_multiyear.py`, add `--concurrency` / `--batch-concurrency` flags; delegate the year loop to `extract_indicators_batch` (target = `(ticker, year)`). Preserve the combined-CSV writer (it consumes the per-year bundles).
- [x] 5.3 Keep single-target invocations (`python scripts/extract_indicators_by_position.py 601398 --year 2023`) on the in-call concurrency path only (no batch pool); confirm output files are unchanged.

## 6. Tests (`test_concurrent_extract.py` or extend `test_llm_indicator_extract.py`)

- [x] 6.1 `test_concurrent_run_equals_sequential`: same fixture, run once at `concurrency=1` and once at `concurrency=4`; assert `indicators`, `missing`, `unresolved`, `skipped` are equal and `call_llm_json` call counts are equal.
- [x] 6.2 `test_per_section_calls_overlap_in_time`: with `concurrency=4` and 3 sections, instrument `call_llm_json` with a sleep + barrier to assert at least two calls are in-flight simultaneously (concurrency actually happens).
- [x] 6.3 `test_cap_bounds_inflight`: with `concurrency=2` and 5 sections, assert at most 2 `call_llm_json` calls are in-flight at any instant (semaphore/counter assertion).
- [x] 6.4 `test_concurrency_one_is_strictly_sequential`: with `concurrency=1`, assert `call_llm_json` invocations are non-overlapping and in section-sorted order.
- [x] 6.5 `test_env_var_sets_concurrency`: with `concurrency=None` and `EXTRACT_CONCURRENCY=3`, assert the effective cap is `3` (via the bundle's `concurrency` field).
- [x] 6.6 `test_call_count_unchanged_by_concurrency`: cold-cache run at `concurrency=4` vs `concurrency=1` → identical `call_llm_json` call count.
- [x] 6.7 `test_bundle_carries_concurrency_field`: assert the bundle has `concurrency: <int>` equal to the resolved cap for both `concurrency=4` and `concurrency=1`.
- [x] 6.8 `test_section_cache_composes_with_concurrency`: after a `concurrency=4` run populates the section cache, a second run (any concurrency) makes zero `call_llm_json` calls (cache dedup holds under concurrency — no duplicate calls for the same section key).
- [x] 6.9 `test_batch_runs_targets_concurrently`: `extract_indicators_batch` with 3 targets at `concurrency=3` asserts overlapping extractions.
- [x] 6.10 `test_batch_isolates_failing_target`: one target raises / returns `{"error": ...}`; assert the other two appear in the result map and the failing one is in `failures`; the call does not raise.
- [x] 6.11 `test_batch_result_is_order_independent`: run the same 3 targets twice; assert identical target→bundle mappings.
- [x] 6.12 `test_batch_empty_targets`: empty `targets` → empty result map and empty `failures`.
- [x] 6.13 `test_batch_cap_defaults_and_respected`: assert default batch cap is `2`; with `concurrency=1` targets run one at a time.
- [x] 6.14 Add a no-network assertion (mirroring `test_no_httpx_request_leaves_process`): the concurrent test suite makes zero real `httpx` requests and requires no `LLM_API_KEY`.

## 7. Documentation

- [x] 7.1 Update `README.md` "Indicator extraction" section: mention the `concurrency` parameter, `EXTRACT_CONCURRENCY` env var (default `4`), the `extract_indicators_batch` function, and the rate-limit caveat (lower the cap on providers that 429; the product `batch × extract` bounds peak in-flight).
- [x] 7.2 Add a "Concurrency" subsection to `docs/indicators-methodology.md` (or the `render_methodology` output) describing the thread-pool model, the `concurrency=1` escape hatch, and the disjoint-section / atomic-cache thread-safety rationale.
- [x] 7.3 Update `scripts/extract_indicators_by_position.py` and `scripts/extract_indicators_multiyear.py` docstrings/`--help` text to document `--concurrency` and `--batch-concurrency`.
- [x] 7.4 Re-render methodology/coverage if the renderer output mentions concurrency: `python indicators_client.py --render-methodology > docs/indicators-methodology.md`.

## 8. Verification

- [x] 8.1 Run `python -m pytest test_llm_indicator_extract.py test_concurrent_extract.py -q` (via `.venv/bin/python -m pytest` per the test-runner memory) and confirm all concurrency tests pass with no network.
- [x] 8.2 Run `openspec validate concurrent-indicator-extract` and confirm the change is valid and apply-ready.
- [x] 8.3 Smoke-run a single-target extraction end-to-end (`python scripts/extract_indicators_by_position.py 601398 --year 2023 --concurrency 4`) and confirm the output bundle/CSV matches a `--concurrency 1` run (modulo the `concurrency` field).
