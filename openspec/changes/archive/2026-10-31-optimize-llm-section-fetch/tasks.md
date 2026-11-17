## 1. Section cache module

- [x] 1.1 Create `llm_section_cache.py` at the repo root with module docstring (mirrors `report_cache.py` style: describe layout, env vars, no-TTL rationale).
- [x] 1.2 Implement `cache_dir() -> Path` returning `report_cache.cache_dir() / "llm_sections"` (auto-create on first use).
- [x] 1.3 Implement `compute_key(pdf_url, section_key, period, wanted_signature, rules_hash) -> str` returning a 32-char SHA1 hex digest.
- [x] 1.4 Implement `cache_path(key: str) -> Path` returning `cache_dir() / f"{key}.json"`.
- [x] 1.5 Implement `_enabled() -> bool` reading `LLM_SECTION_CACHE` env var (default enabled, only the literal string `"off"` disables).
- [x] 1.6 Implement `get(pdf_url, section_key, period, wanted_signature, rules_hash) -> Optional[dict]` reading the cache file and validating the meta block; return `None` on miss, on disabled, on JSON error, or on key mismatch.
- [x] 1.7 Implement `put(pdf_url, section_key, period, wanted_signature, rules_hash, records: list[dict]) -> None` writing `{meta, records}` atomically (temp + `os.replace`); swallow + debug-log on failure.
- [x] 1.8 Implement `merge_subset(cached: dict, delta_wanted: list[str], delta_records: list[dict]) -> list[dict]` returning the merged records keyed by normalized indicator name (delta wins on conflict).

## 2. Wire cache into `_llm_extract_section`

- [x] 2.1 Add optional `pdf_url`, `section_key` parameters to `_llm_extract_section` (both default to `None` to preserve the existing call site). When provided, compute the cache key and call `llm_section_cache.get` first.
- [x] 2.2 On cache hit with all wanted indicators present, return the cached `records` mapped to rule names (skip the `call_llm_json` call entirely) and emit a debug log.
- [x] 2.3 On cache hit with a partial overlap, compute the delta (wanted − cached.wanted), call `call_llm_json` with the delta only, merge via `merge_subset`, write the merged set to the cache under the new `wanted_signature`, and return the merged result.
- [x] 2.4 On cache miss, call `call_llm_json` as today, then write the full response to the cache (under the current `wanted_signature`).
- [x] 2.5 Propagate `pdf_url` and `section_key` from `extract_indicators` (the `ctx.pdf_url` + the resolved section title) so the cache key is populated.

## 3. Subset reuse in `extract_indicators`

- [x] 3.1 In the per-section loop (line ~945), pass `pdf_url=ctx.pdf_url` and `section_key=<resolved title>` to `_llm_extract_section`.
- [x] 3.2 Increment a local `section_cache_reuse` counter by the number of cached records reused (delta-wanted size subtracted from total wanted size).
- [x] 3.3 After the loop, add `bundle["section_cache_reuse"] = section_cache_reuse` to the returned bundle.
- [x] 3.4 In `extract_indicators_by_position`, propagate `section_cache_reuse` from the inner `extract_indicators` bundle to the outer bundle (so the position-extraction entry point surfaces it too).
- [x] 3.5 In the python-mode branch (line ~930), the section cache is still consulted (python rules are dispatched individually, but the LLM-extractable indicators in the same section are not python; verify the LLM path is still hit when extractor_mode=="python" but the rule is LLM). Confirm via test that `section_cache_reuse` only counts LLM records.

## 4. `get_indicator` single-indicator path

- [x] 4.1 In `_run_extractor`, when `effective == "llm"`, build the single-rule `wanted_signature` and check the section cache before calling `_llm_extract_section`.
- [x] 4.2 On a hit, return the cached record with a `note: "llm-section-cache"` to distinguish it from a fresh LLM call.
- [x] 4.3 On a miss, fall through to `_llm_extract_section(text, [rule], period)` and cache the result.
- [x] 4.4 Propagate `pdf_url` and `section_key` from `_resolve_via_report` (which already has the matched section title) to `_run_extractor`.
- [x] 4.5 Verify `get_indicator` for a `report`-source rule whose section was previously extracted returns the same value as the bundle (no LLM call).

## 5. Tests (in `test_llm_indicator_extract.py`)

- [x] 5.1 Add `test_section_cache_hit_avoids_second_llm_call`: two consecutive `extract_indicators_by_position` runs with the same wanted set; assert `call_llm_json` is invoked exactly once across both runs.
- [x] 5.2 Add `test_section_cache_subset_reuse_calls_llm_only_for_delta`: first run caches `{A,B,C}`, second run requests `{A,B,D}`; assert `call_llm_json` is invoked once with `wanted = [D]` only, and the returned `A,B` match the cached values.
- [x] 5.3 Add `test_section_cache_get_indicator_no_llm_call`: after a full extraction, call `get_indicator("资产总计", "000000", 2023)`; assert `call_llm_json` is not invoked and the value matches the bundle.
- [x] 5.4 Add `test_section_cache_invalidated_by_rules_hash_change`: write a cache entry under rules_hash `h1`, swap the rule set so `rules_hash()` returns `h2`, run extraction; assert `call_llm_json` is invoked and the new entry is written under `h2`.
- [x] 5.5 Add `test_section_cache_disabled_via_env_var`: with `LLM_SECTION_CACHE=off`, run extraction twice; assert `call_llm_json` is invoked once per run (no cross-run reuse).
- [x] 5.6 Add `test_section_cache_graceful_write_failure`: patch the cache directory to be read-only; assert extraction still completes and returns the LLM response.
- [x] 5.7 Add `test_bundle_section_cache_reuse_field`: assert the returned bundle contains `section_cache_reuse: <int>` and the count equals the number of cached records reused.
- [x] 5.8 Update the existing `test_no_httpx_request_leaves_process` to set `LLM_SECTION_CACHE=off` in the fixture (the new default is enabled, which would interact with the per-test temp cache directory).

## 6. Documentation

- [x] 6.1 Update `README.md` "Indicator extraction" section to mention the section cache and the `LLM_SECTION_CACHE=off` env var.
- [x] 6.2 Add a short subsection to `docs/indicators-methodology.md` (or `render_methodology` output) describing the cache layout and key scheme.
- [x] 6.3 Add a "Section cache" entry to the "Refresh" block in the methodology doc that points at `llm_section_cache.clear_*` (deferred — placeholder for follow-up).
