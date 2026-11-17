## Context

`extract_indicators` (`indicators_client.py`) is the engine that resolves many indicators for one company/year in one pass. Its report pass groups `report`-type rules by resolved section and issues **one LLM call per section** (`_llm_extract_section` → `_llm_fetch_records` → `cnreport_tools.call_llm_json`, a blocking `httpx.post` with a 120 s timeout). The `optimize-llm-section-fetch` change added a persistent section cache so that *re-runs* are nearly free, but a **cold first pass** still walks `for sec in sections:` sequentially (`indicators_client.py:1040`). The `akshare` group is the same shape — `for r in akshare_rules:` (`indicators_client.py:995`), each an independent network call. With N sections the cold-pass wall-clock is `N × latency`; the calls are independent and I/O-bound, so this is pure serial latency, not throughput-limited work.

The batch scripts (`scripts/extract_indicators_by_position.py --from-file`, `scripts/extract_indicators_multiyear.py --years`) layer a second sequential loop on top — many `(company, year)` extractions one after another.

The codebase is **synchronous end-to-end**: `httpx.post` blocking, `report_cache` sync file I/O, `financials_client` sync. The concurrency surface is clean: `call_llm_json` creates a fresh `httpx.post` per call (no shared client), `report_cache`/`llm_section_cache` use atomic `tmp + os.replace` writes to **distinct** keys, `_RULES_CACHE` is read-only after first load, and `financials_client.get_statements` has no module-level mutable state.

## Goals / Non-Goals

**Goals:**
- Cut cold-pass wall-clock for one `extract_indicators` call from `O(sections × LLM_latency)` to `O(LLM_latency)` bounded by a worker cap, by running the independent per-section LLM calls (and the `akshare` calls) concurrently.
- Provide a new `extract_indicators_batch(targets, ...)` function so batch script runs stop being sequential across `(company, year)`.
- Keep the change backwards-compatible: identical return shape (additive `concurrency` field only), deterministic output (a concurrent run produces a bundle equal to the sequential run on the same fixture), and `concurrency=1` as an exact sequential escape hatch.
- Stay within the existing thread-safety boundary — no new locks, no shared mutable state mutated from workers.

**Non-Goals:**
- No asyncio rewrite of the engine or `call_llm_json` (sync stays sync; threads are the minimal fit for I/O-bound concurrency).
- No change to the **number** of LLM calls — still exactly one per section (the section cache remains the dedup boundary). Concurrency only changes *when* independent calls are issued.
- No memoization of `financials_client.get_statements` within a call (orthogonal perf win; rules sharing a statement re-fetch it — noted as future work).
- No parallelizing the python-extractor branch (CPU-bound, fast, low benefit) or the computed-rules multi-pass (local arithmetic, ordered by data dependency).
- No change to the bundle cache fast-path (`cached: true` returns before any section work).

## Decisions

### D1. Threads (`ThreadPoolExecutor`), not asyncio / multiprocessing
The work is I/O-bound (HTTP waits, file I/O). The codebase is fully sync. A thread pool is the minimal, idiomatic fit: `concurrent.futures.ThreadPoolExecutor`, stdlib, no dependency. The GIL is irrelevant — sockets release it during reads. Considered: (a) asyncio rewrite — rejected, high blast-radius, touches `call_llm_json`/`report_cache`/every extractor; (b) multiprocessing — rejected, I/O-bound not CPU-bound, plus pickle overhead and per-process state duplication. Threads win on simplicity and reversibility (`concurrency=1` disables them with zero behavioral change).

### D2. Per-section map → merge in main thread (no shared mutation)
Each section's work is wrapped in a closure `_extract_one_section(sec)` that captures its `rules_in_sec`, `section_text_cache[sec]`, `ctx`, `pdf_url`, and returns `{indicator_name: value_obj}`. The pool maps this over `sorted(set(section_of.values()))`; the main thread merges `results.update(sub)` per returned section. Workers never touch the shared `results` dict, so no locking is needed. Output determinism: the `indicators` dict is built in `sorted(sections)` order regardless of completion order → a concurrent run yields a bundle byte-equal to the sequential run on the same fixture (no timing fields are emitted). The `akshare` group uses the identical pattern over its rules. The `section_cache_reuse` counter is accumulated from each sub-result in the main thread (not incremented inside workers).

### D3. `concurrency` parameter + `EXTRACT_CONCURRENCY` env var; `concurrency<=1` runs inline
`extract_indicators` and `extract_indicators_by_position` gain `concurrency: int | None = None`; when `None` it reads `int(os.environ.get("EXTRACT_CONCURRENCY", "4"))`. To make `concurrency=1` an **exact** sequential reproduction (deterministic call order, for tests and rate-fragile providers), the dispatch special-cases `concurrency <= 1` to run the loop inline with no pool. A cheap guard skips the pool entirely when `len(sections) <= 1`. The bundle reports the effective cap via a new `concurrency: <int>` field.

### D4. Section cache is the dedup boundary; concurrency does not change call counts
Because sections are disjoint by construction (each `sec` is a distinct resolved section title), no two workers ever read/write the same `llm_section_cache` key, so there is no cache-write race. The bundle-cache fast-path (`report_cache.get_cached_indicators` → `cached: true`) returns before any pool work. `_llm_extract_section`'s own read-then-write is unchanged; even hypothetically, `os.replace` is atomic so the worst case is a duplicate LLM call, never corruption. This preserves the `optimize-llm-section-fetch` contract verbatim.

### D5. `extract_indicators_batch(targets, ...)` — shared cap, per-target isolation
New public function. Signature: `extract_indicators_batch(targets: list[dict|tuple], *, concurrency=None, ...)` where each target is `(ticker, year[, form])`. It maps `extract_indicators_by_position` (or `extract_indicators`) over targets with a `ThreadPoolExecutor`, returns `{target_key: bundle}` plus a `failures: list[{target, error}]`. A target that raises or returns `{"error": ...}` is recorded in `failures` and skipped — never aborts the batch. The result is an order-independent keyed map. The batch scripts' loops delegate to it.

### D6. Effective-concurrency product is documented, not silently capped
`extract_indicators_batch` and the in-call concurrency use **separate** pools. Peak in-flight LLM calls can therefore reach `batch_concurrency × extract_concurrency`. Rather than build a cross-layer semaphore (complexity, and the right global bound is provider-specific), we document the product and default the batch cap low (default `2`) so `2 × 4 = 8` peak with defaults. Callers who hit 429s lower either cap. This keeps each layer independently simple and tunable.

## Risks / Trade-offs

- **[LLM provider 429 rate-limiting under concurrent load]** → `call_llm_json` already retries 429 honoring `Retry-After` (up to `max_retries`). Default in-call cap `4` keeps in-flight ≤4; batch default `2`; `EXTRACT_CONCURRENCY=1` is the full escape hatch. Document the caveat in README + methodology.
- **[Non-deterministic interleaving makes a flaky failure hard to reproduce]** → `concurrency=1` reproduces the exact sequential path; tests assert a concurrent run is result-equal to a `concurrency=1` run on the same fixture (same indicator values, same `missing`/`unresolved`/`skipped`, same call count).
- **[akshare/Sina thread-safety is not guaranteed by akshare internals]** → no module-level mutable state observed at our boundary (`financials_client.get_statements` is stateless), but akshare's own globals are out of our control. Mitigation: if a flaky akshare failure appears under concurrency, gate the akshare map behind a smaller cap or make it sequential via a dedicated flag without disabling LLM concurrency. Flag as the first thing to check if a concurrency-only failure surfaces.
- **[Section-cache write race for the same key]** → not reachable (disjoint sections); if ever reachable, `os.replace` atomicity bounds the damage to a duplicate call, never corruption.
- **[Thread-pool overhead for tiny rule sets]** → guarded: skip the pool when `len(sections) <= 1` (and `len(akshare_rules) <= 1`).
- **[Default-on concurrency changes runtime characteristics for existing callers]** → return shape is additive-only (`concurrency` field); behavior for a cached bundle is unchanged (fast-path returns pre-pool). Rollback is `EXTRACT_CONCURRENCY=1`, no code revert needed.

## Migration Plan

Backwards-compatible by construction — no data migration, no API removal. Deploy steps:
1. Ship the concurrent dispatch behind the `concurrency` parameter (default `4`, env-overridable).
2. Existing callers keep working unchanged; the `concurrency` field is additive and safe to ignore.
3. Rollback (if a provider or akshare regression appears): set `EXTRACT_CONCURRENCY=1` (or pass `concurrency=1`) — restores the exact sequential behavior with no code revert.

## Open Questions

- **Global vs. layered cap.** Should there be one global semaphore bounding total in-flight LLM calls (instead of the documented product in D6)? A global cap is safer for rate-limited providers but adds cross-layer coupling. Proposed for this change: document the product, keep layers independent; revisit a global semaphore if 429s become common in practice.
- **`extract_indicators_batch` return shape.** `{target_key: bundle} + failures` vs. a list preserving input order. Proposed: keyed map (order-independent, natural for lookups) plus a `failures` list. Confirm during implementation.
- **Should the batch function default to `extract_indicators` or `extract_indicators_by_position`?** The scripts use the position path; `extract_indicators_batch` should accept a `csv_path`/`indicators` and delegate to the position extractor when given, else to `extract_indicators`. Resolve at task time.
