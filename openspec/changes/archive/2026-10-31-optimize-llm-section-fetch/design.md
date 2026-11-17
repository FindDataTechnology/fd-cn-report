## Context

The LLM-extraction path inside `indicators_client` already guarantees "one call per section" **within a single run** (see [`_llm_extract_section`](file:///Users/chengsishi/finddata/cnreport/indicators_client.py#L440) and the `extract_indicators` per-section loop at line 945). That guarantee is broken in two practical cases:

1. **Cross-run**: the bundle cache in [`report_cache`](file:///Users/chengsishi/finddata/cnreport/report_cache.py#L160) (`{stem}.indicators.json`) is keyed by `rules_hash`, so requesting a *different* indicator subset in the same section invalidates the bundle and triggers a fresh LLM call — even though the section text and the previously returned records are identical.
2. **Single-indicator entry point**: [`_run_extractor`](file:///Users/chengsishi/finddata/cnreport/indicators_client.py#L517) falls back to `_llm_extract_section(section_text, [rule], period)` with a single rule when no `llm_cache` is provided. This is the path used by [`get_indicator`](file:///Users/chengsishi/finddata/cnreport/indicators_client.py#L786) and any external caller that resolves rules one at a time. The single-rule LLM call duplicates work that the section-level batched call would have done in a single request.

LLM calls are the dominant cost in the pipeline (network latency + paid tokens). The fix is a persistent section-level cache that stores the raw `{records: [...]}` response and is consulted before any HTTP call.

## Goals / Non-Goals

**Goals:**
- Persist the raw `call_llm_json` response per section, keyed by `(pdf_url, section_key, period, wanted_signature, rules_hash)`.
- Reuse the cached response on subsequent extractions of the same section (cross-run, single-indicator, or subset).
- Subset reuse: when the wanted set grows, call the LLM only for the missing indicators and merge.
- Report reuse counts in the bundle as `section_cache_reuse: <int>` so callers can see when the cache saved an LLM call.
- Preserve the existing no-network / no-key test contract; cache must be bypassable via `LLM_SECTION_CACHE=off`.

**Non-Goals:**
- TTL or auto-pruning of cache files (CNINFO reports are immutable; cache bloat is a separate concern).
- Cross-PDF reuse (different `pdf_url` = different cache namespace, even if the text is identical).
- Changing the LLM prompt shape or the `records` response schema.
- Caching the bundle result — the existing `report_cache.write_cached_indicators` is unchanged.
- Live LLM-call instrumentation beyond `section_cache_reuse` and the existing `note` field.

## Decisions

**Decision 1 — New module `llm_section_cache.py`, sibling to `report_cache.py`.**
*Why:* a focused module with three helpers (`get`, `put`, `disable_check`) keeps the LLM-cache concerns out of `indicators_client` and out of `report_cache`. `report_cache` stays the place for PDF/text/outline/bundle; the new module is for LLM responses only. *Alternative considered:* add a `section_cache.py` to `report_cache.py` — rejected: mixes LLM and PDF concerns in one module and bloats `report_cache.py`.

**Decision 2 — Cache files live under `report_cache.cache_dir() / "llm_sections"`.**
*Why:* sharing the cache directory means the existing `CNREPORT_CACHE_DIR` env var, the test fixture's temp directory, and the no-network test seam all work for the new cache without changes. A sub-directory keeps the namespace clean (`url_*.txt` vs `url_*.llm_section.json`). *Alternative considered:* a separate top-level `.cache/llm_sections/` — rejected: two env vars to manage in tests.

**Decision 3 — Cache key = SHA1 of `pdf_url|section_key|period|wanted_signature|rules_hash`.**
*Why:* the key must change if any of these changes, otherwise stale records would be returned. `pdf_url` distinguishes reports; `section_key` (e.g. `"合并资产负债表"`) distinguishes sections within a report; `period` distinguishes Q1/Q2/Q3/year-end; `wanted_signature` is the sorted-comma-joined indicator names; `rules_hash` invalidates the cache when `indicator_rules.json` is edited. *Alternative considered:* include section-text hash instead of `pdf_url + section_key` — rejected: too sensitive to whitespace/pypdf drift; the `(pdf_url, section_key)` pair is stable and intent-preserving.

**Decision 4 — Cache file format: `{meta, records}`.**
```
{
  "meta": {
    "pdf_url": "...",
    "section_key": "...",
    "period": "annual",
    "wanted": ["A", "B", "C"],
    "rules_hash": "abcd1234",
    "cached_at": "2026-07-06T10:00:00Z"
  },
  "records": [
    {"indicator": "A", "value": 1, "unit": "元", "period": "annual"},
    {"indicator": "B", "value": 2, "unit": "元", "period": "annual"},
    {"indicator": "C", "value": null, "unit": "元", "period": "annual"}
  ]
}
```
*Why:* storing `meta` enables key-mismatch detection without recomputing; storing `records` (not the raw LLM text) means consumers don't re-parse JSON on every read. The `wanted` array is preserved verbatim so subset reuse can compute the intersection. *Alternative considered:* store the raw LLM string and re-parse on read — rejected: every read pays the parse cost.

**Decision 5 — Subset reuse logic: intersect first, then call LLM for the delta.**
*When the cache has `{A,B,C}` and the run wants `{A,B,D}`:*
1. Build `wanted_signature(run) = "A,B,D"`.
2. Compute `delta = wanted - cache.wanted`. Here `delta = {D}`.
3. If `delta` is empty: return the cache records (full reuse).
4. Otherwise: call `_llm_extract_section(text, [rule for rule in rules if rule.name in delta], period)`.
5. Merge the delta records with the cache records, write the merged set under the new `wanted_signature`, and return the merge.

*Why:* keeps the LLM call as small as possible. The merge is a simple dict-merge by normalized indicator name (reusing `_normalize` from `indicators_client`). *Alternative considered:* always re-call with the full wanted set — rejected: defeats the cache.

**Decision 6 — `LLM_SECTION_CACHE=off` env var opts out.**
*Why:* tests need a deterministic no-cache path. Operators with strict data-retention policies may also want to disable the on-disk cache. *Default:* enabled. The env var is read in `llm_section_cache._enabled()` and gates both reads and writes.

**Decision 7 — Atomic writes + graceful failure.**
*Why:* partial writes corrupt the JSON and break subsequent reads; the existing `_atomic_write` pattern in `report_cache.py:78` is the right primitive. If the cache directory is not writable, the failure is logged at debug level and the extractor falls through to the LLM call — never raise. *Alternative considered:* raise on cache failure — rejected: a broken cache must never block extraction.

**Decision 8 — `get_indicator` integration via the section cache.**
*When `get_indicator` resolves a `report`-source rule:*
1. Build a "single-rule wanted" cache key.
2. Check the section cache; on hit, return the cached record.
3. On miss, fall through to `_llm_extract_section` (single-rule call, then cache).

*Why:* the section cache unifies the batched and single-indicator paths on the same persistence layer. The existing `llm_cache` parameter on `_run_extractor` is preserved for the in-process batched path; the new section cache covers the cross-process / cross-run case.

**Decision 9 — `section_cache_reuse: <int>` field in the bundle.**
*Why:* visibility. Callers (and the CLI script) can see when the section cache saved an LLM call even when the bundle cache missed. The integer is the count of indicator records served from the section cache (sum of `len(records)` reused across all sections in this run). *Alternative considered:* boolean — rejected: the count is more useful for debugging and regression.

## Risks / Trade-offs

- [Cache bloat across rule-set edits] → Mitigation: `rules_hash` is part of the key, so old files are orphaned but never read. A future change can add a `clear_orphans` tool; out of scope here.
- [Cache directory shared between PDFs and LLM sections] → Mitigation: sub-directory `llm_sections/` keeps the namespaces separate; `report_cache.list_cache` only globs `*.txt` so the new files don't appear there.
- [Subset merge drops `note` field] → Mitigation: cached records include a `note: "llm-section-cache"` so the provenance is preserved. When a delta is fetched, the delta's `note` is `"llm"` and merged with the cache's `note` for that record (the fresh `note` wins).
- [Test interference from a populated cache directory] → Mitigation: tests set `CNREPORT_CACHE_DIR` to a temp dir and `LLM_SECTION_CACHE=off` for tests that must be deterministic. The new "cross-run reuse" test sets `LLM_SECTION_CACHE=on` (the default) and uses its own temp dir.
- [Concurrent runs sharing the same cache] → Mitigation: `_atomic_write` (write to `.tmp` then `os.replace`) makes per-file writes safe. Two concurrent runs may both miss on the same key and both call the LLM; the second write wins. This matches `report_cache` semantics.
- [Section key naming drift] → Mitigation: `section_key` is the canonical title returned by `resolve_selector` / `resolve_statement` (e.g. `"合并资产负债表"`), which is stable across runs because the outline is content-driven and the canonical-match path is deterministic.

## Migration Plan

- **Deploy:** land the new module + integration in one commit. No migration of old data (old cache files are not read by the new code).
- **Rollback:** delete `llm_section_cache.py` and revert `indicators_client.py`. The bundle cache continues to work; behavior regresses to the pre-change "one LLM call per run per indicator subset" — equivalent to the pre-change state.
- **Operational:** `LLM_SECTION_CACHE=off` provides a runtime kill switch. `report_cache.clear_cache` does not touch the new files; if operators need to evict LLM sections, the `llm_sections/` sub-directory can be removed by hand.

## Open Questions

- Should the cache key include a hash of the section text, or just the (pdf_url, section_key) pair? The current design uses the pair to avoid being brittle to pypdf whitespace drift. If two PDFs have the same `pdf_url` but different extracted text (rare, but possible if the upstream re-issues the file), the cache will be stale. **Decision deferred:** track via a follow-up; current design accepts the rare staleness.
- Should we expose a `clear_llm_section_cache` helper mirroring `report_cache.clear_cache`? **Decision deferred:** not required by the spec; add when needed.
