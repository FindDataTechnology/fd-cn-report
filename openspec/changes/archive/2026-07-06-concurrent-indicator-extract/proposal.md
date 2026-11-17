## Why

`extract_indicators` already batches every LLM query in a section into one call (one prompt → one `records` response, per `optimize-llm-section-fetch`), and the section cache makes re-runs nearly free. But on a **first pass** — cache cold — the per-section LLM calls still run **sequentially** in `for sec in sections:` (`indicators_client.py:1040`), and the `akshare` group runs sequentially in `for r in akshare_rules:` (`indicators_client.py:995`). Each section's LLM call is an independent, I/O-bound HTTP round-trip (`call_llm_json`, 120 s timeout); with N sections the cold-pass wall-clock is `N × latency` when it could be `~1 × latency` bounded by a worker cap. The same sequential loop dominates the batch scripts (`extract_indicators_by_position --from-file`, `extract_indicators_multiyear`), where many (company, year) extractions run one after another.

## What Changes

- Run the **per-section LLM calls concurrently** inside `extract_indicators` using a thread pool (each section is independent: distinct section text, disjoint indicator names, distinct section-cache keys). Workers return a per-section sub-result that the main thread merges into `results` — no shared dict mutation.
- Run the **`akshare` group concurrently** the same way (independent per-rule network I/O).
- Add a `concurrency: int` parameter to `extract_indicators` and `extract_indicators_by_position`, backed by an `EXTRACT_CONCURRENCY` env var (default `4`). `concurrency=1` reproduces the current sequential behavior exactly (for debugging / reproducibility / rate-limit-fragile providers).
- Add a new **`extract_indicators_batch(targets, ...)`** function that runs many `(ticker, year[, form])` extractions concurrently with a shared cap and returns `{target_key: bundle}`. Wire it into the `--from-file` path of `scripts/extract_indicators_by_position.py` and the year loop of `scripts/extract_indicators_multiyear.py` so batch runs stop being sequential.
- Surface a `concurrency: <int>` field in the bundle so callers can see when parallelism was applied (distinct from `cached` / `section_cache_reuse`).
- Keep the python-extractor branch sequential (CPU-bound, fast, low benefit) and keep the bundle-cache fast-path unchanged (a `cached: true` bundle still returns before any section work).
- **No breaking changes** to public return shapes; `concurrency` defaults to `1`-equivalent behavior only when explicitly requested. Default is concurrent.

## Capabilities

### New Capabilities
- `concurrent-extract-batch`: a `extract_indicators_batch(targets, concurrency=..., ...)` entry point that runs many `(ticker, year[, form])` extractions concurrently with a shared worker cap, returns a map keyed by target, isolates per-target failures (one target's error never aborts the batch), and feeds the batch scripts.

### Modified Capabilities
- `indicator-batch-extract`: the extraction pass now runs its per-section LLM calls and `akshare` calls concurrently up to a configurable cap (`concurrency` parameter + `EXTRACT_CONCURRENCY` env var, default `4`); `concurrency=1` reproduces the prior sequential behavior; the bundle reports the cap used via a new `concurrency` field. The one-call-per-section count and the section-cache reuse contract are unchanged — concurrency only changes *when* the independent calls are issued, not how many are issued.

## Impact

- `indicators_client.py`: `extract_indicators` gains the concurrent per-section + akshare dispatch (thread pool, merge-in-main-thread) and a `concurrency` parameter; `extract_indicators_by_position` propagates `concurrency`; new `extract_indicators_batch`; bundle gains `concurrency` field.
- `scripts/extract_indicators_by_position.py`: `--from-file` path delegates to `extract_indicators_batch`; add `--concurrency` CLI flag.
- `scripts/extract_indicators_multiyear.py`: year loop delegates to `extract_indicators_batch`; add `--concurrency` CLI flag.
- `cnreport_tools.call_llm_json`: no change (already thread-safe — fresh `httpx.post` per call, no shared client/state). `report_cache` / `llm_section_cache`: no change (atomic `os.replace` writes to distinct keys; already the concurrency-safe boundary established by `optimize-llm-section-fetch`). `_RULES_CACHE`: read-only after first load (idempotent under concurrent first-access).
- New tests in `test_llm_indicator_extract.py` (or a new `test_concurrent_extract.py`): concurrent run is result-equivalent to sequential; worker cap is respected; `EXTRACT_CONCURRENCY=1` reproduces sequential call order; section cache + concurrency compose (still one LLM call per section, no duplicates); `extract_indicators_batch` runs targets concurrently, isolates a failing target, and returns an order-independent map.
- Docs: `README.md` "Indicator extraction" + `docs/indicators-methodology.md` mention the `concurrency` parameter, `EXTRACT_CONCURRENCY` env var, and the rate-limit caveat (lower the cap on providers that 429).
- No new dependencies (`concurrent.futures` is stdlib). No new external services. Default-on concurrency may increase LLM provider request rate up to the cap; the existing 429 retry-with-`Retry-After` in `call_llm_json` absorbs transient rate-limiting, and `concurrency=1` is the escape hatch.
