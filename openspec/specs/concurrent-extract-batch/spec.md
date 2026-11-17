# concurrent-extract-batch

## Purpose

Run many `(ticker, year[, form])` indicator extractions concurrently via the `extract_indicators_batch` function. Each target is extracted independently (its own PDF fetch and per-section LLM calls) and runs in parallel up to a worker cap; a failing target is isolated rather than aborting the batch. Powers the `--from-file` path of `scripts/extract_indicators_by_position.py` and the year loop of `scripts/extract_indicators_multiyear.py`.

## Requirements

### Requirement: Batch extraction runs many targets concurrently with per-target isolation
The system SHALL provide `extract_indicators_batch(targets, ...)` that runs many `(ticker, year[, form])` extractions concurrently up to a worker cap. A target whose extraction raises an exception, or returns a bundle containing an `error` key, SHALL be recorded in a `failures` list (with the target identifier and error message) and SHALL NOT abort the remaining targets. The function SHALL return a map keyed by a target identifier to that target's bundle, alongside the `failures` list. The result map SHALL be order-independent — identical regardless of target completion order.

#### Scenario: Many targets run concurrently
- **WHEN** `extract_indicators_batch` is called with three targets at `concurrency=3`
- **THEN** the three underlying extractions are issued concurrently (their execution overlaps in time).

#### Scenario: A failing target is isolated
- **WHEN** `extract_indicators_batch` runs three targets and one target's extraction raises while two succeed
- **THEN** the two successful bundles appear in the result map, the failing target appears in `failures` with its error, and the batch call does not raise.

#### Scenario: Result is order-independent
- **WHEN** the same three targets are run through `extract_indicators_batch` twice
- **THEN** the result map contains the same target-to-bundle mappings both times.

#### Scenario: Empty targets yields an empty result
- **WHEN** `extract_indicators_batch` is called with an empty `targets` list
- **THEN** the result map and the `failures` list are both empty.

### Requirement: Batch concurrency is configurable and defaults conservatively
The batch worker cap SHALL be set by a `concurrency` parameter, falling back to an environment variable (default `2`). Because the batch pool and the per-extraction (`extract_indicators`) pool are independent, the peak in-flight LLM call count is bounded by the product of the two caps; the system documentation SHALL state this product so callers can tune against provider rate limits.

#### Scenario: Batch cap defaults to 2
- **WHEN** `concurrency` is omitted and no overriding environment variable is set
- **THEN** at most two extractions run concurrently.

#### Scenario: Batch cap is respected
- **WHEN** `concurrency=1` and three targets are supplied
- **THEN** the targets run one at a time (no overlap).
