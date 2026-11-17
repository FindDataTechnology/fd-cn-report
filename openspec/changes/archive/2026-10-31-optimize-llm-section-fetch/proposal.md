## Why

`indicators_client._llm_extract_section` already collapses every LLM query in one section into a single call (one prompt → one `records` response), but that guarantee is **per run** and **per indicator set**:

- `_run_extractor` falls back to `_llm_extract_section(section_text, [rule], period)` with a single rule when no `llm_cache` is passed (the `get_indicator` / `_resolve_via_report` path). That defeats the batching for any caller that resolves one indicator at a time.
- `extract_indicators` already batches correctly, but its result is cached at the **bundle** level (`report_cache.get_cached_indicators(stem, rules_hash)`). Asking for a *different* subset of indicators in the same section invalidates the bundle cache and triggers a fresh LLM call — even though the section text and the previously returned indicators are identical.
- LLM calls are the most expensive part of the pipeline (network + paid tokens); redundant calls are the dominant cost on iteration and on `get_indicator` loops.

We want one LLM call per (section text + wanted indicator set), reused across runs and across single-indicator entry points, so the same section text is fetched from the LLM at most once for any given indicator set.

## What Changes

- Introduce a **persistent, on-disk LLM section cache** (`llm_section_cache.py`) keyed by `(pdf_url, section_key, period, wanted_signature)` that stores the raw `{records: [...]}` response returned by `call_llm_json`. Cache files live under `report_cache`'s cache directory so they share the existing lifecycle and the no-network test seam.
- Wire the cache into `indicators_client._llm_extract_section`: compute the key from the section text + wanted list, look up the cache first, call `call_llm_json` only on a miss, and write the result back. Cache writes are atomic (`tmp` + `os.replace`) and silently swallowed on failure so a broken cache never blocks extraction.
- Add a **section-level reuse path** in `extract_indicators`: after resolving a section's text, intersect the wanted indicators with the cache; only the missing subset goes to the LLM, and the merged result populates `results`. The bundle cache (`report_cache.write_cached_indicators`) is unchanged — it still keys on the indicator set, but a hit no longer implies a fresh LLM call.
- Extend `get_indicator` / `_resolve_via_report` to use the same section cache. A single-indicator resolution for an LLM-extracted report rule will hit the cache if the section was previously extracted, avoiding a redundant per-rule LLM call.
- Add cache invalidation by `report_cache.rules_hash` change: when the rule set's hash changes, the section cache is rebuilt (the section text is the same but the wanted set or interpretation may differ).
- Tests in `test_llm_indicator_extract.py`: assert (a) one LLM call across two consecutive `extract_indicators_by_position` runs with overlapping indicator sets, (b) `get_indicator` for a previously-extracted rule does not invoke `call_llm_json`, (c) cache is keyed by section text + wanted list (changing either invalidates), (d) cache write failure does not break extraction.

## Capabilities

### New Capabilities
- `llm-section-cache`: persistent on-disk cache for the `{records:[...]}` response of `call_llm_json`, keyed by `(pdf_url, section_key, period, wanted_signature)`, with atomic writes, graceful degradation on failure, and integration into `extract_indicators` (subset reuse) and `get_indicator` (single-rule reuse).

### Modified Capabilities
- `llm-indicator-extract`: the existing one-call-per-section contract now also covers **cross-run reuse** — the same section + wanted set, with the same rule-set hash, is satisfied from the cache without a second LLM call. Add a delta spec requiring the cache lookup before any LLM HTTP request.

## Impact

- `indicators_client.py`: `_llm_extract_section` gains cache lookup + write; `extract_indicators` gains subset intersection before the per-section LLM call; `_resolve_via_report` checks the section cache for single-indicator resolution.
- New module: `llm_section_cache.py` (read/write/lookup helpers; no business logic).
- `report_cache.py`: no API change, but section cache files share its `cache_dir`.
- `test_llm_indicator_extract.py`: new cases for cross-run reuse, single-indicator reuse, key invalidation, and graceful degradation.
- Public surface unchanged: `extract_indicators`, `extract_indicators_by_position`, `get_indicator` keep their return shapes. The bundle cache (`cached: true`) still indicates a full bundle hit; a **partial** reuse is reported in the bundle as a new `section_cache_reuse: <int>` field so callers can see when only the section cache (not the bundle cache) saved an LLM call.
- No new dependencies; uses `hashlib`, `json`, `pathlib` (already in use).
- Backwards-compatible: callers that don't read `section_cache_reuse` are unaffected; old cache files are ignored (cache schema is new and additive).
