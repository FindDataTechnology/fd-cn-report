## ADDED Requirements

### Requirement: Extraction passes run concurrently up to a configurable cap
For one `extract_indicators` call, the system SHALL run the per-section LLM extraction calls and the per-rule `akshare` extraction calls concurrently, up to a worker cap. The cap SHALL be determined by the `concurrency` parameter, falling back to the `EXTRACT_CONCURRENCY` environment variable (default `4`). When the resolved cap is `1` or fewer, the system SHALL run the passes inline with no thread pool, reproducing the prior sequential behavior and call order. Concurrency SHALL NOT change the number of LLM calls issued — exactly one call per section remains, and the section cache is the deduplication boundary. Concurrency SHALL NOT change extraction results: a run with `concurrency > 1` SHALL produce `indicators`, `missing`, `unresolved`, and `skipped` equal to a run with `concurrency = 1` on the same inputs.

#### Scenario: Per-section LLM calls run concurrently
- **WHEN** `extract_indicators` runs for a fixture with three distinct report sections at `concurrency=4`
- **THEN** the three per-section `call_llm_json` invocations are issued concurrently (their execution overlaps in time, rather than running strictly one-after-another), and exactly three calls are made (one per section).

#### Scenario: concurrency=1 reproduces sequential behavior
- **WHEN** the same fixture runs at `concurrency=1`
- **THEN** `call_llm_json` is invoked in section-sorted order with no overlap, and the returned `indicators`, `missing`, `unresolved`, and `skipped` are equal to those from the `concurrency=4` run.

#### Scenario: Cap bounds in-flight calls
- **WHEN** `extract_indicators` runs at `concurrency=2` against five distinct sections
- **THEN** no more than two `call_llm_json` calls are in-flight at any instant.

#### Scenario: Environment variable supplies the cap
- **WHEN** the `concurrency` parameter is omitted and `EXTRACT_CONCURRENCY=3` is set
- **THEN** the effective worker cap is `3`.

#### Scenario: Call count is unchanged by concurrency
- **WHEN** a cold-cache extraction runs once at `concurrency=4` and once at `concurrency=1` on the same fixture
- **THEN** the total number of `call_llm_json` calls is identical between the two runs.

### Requirement: Bundle reports the concurrency cap used
The bundle returned by `extract_indicators` and `extract_indicators_by_position` SHALL include a `concurrency: <int>` field set to the effective worker cap used for the extraction pass. The field SHALL be `1` when sequential mode ran. The field is additive and SHALL NOT alter the existing header fields or return shape.

#### Scenario: Bundle carries the concurrency field
- **WHEN** `extract_indicators` runs with `concurrency=4`
- **THEN** the returned bundle contains `"concurrency": 4`.

#### Scenario: Sequential mode reports 1
- **WHEN** `extract_indicators` runs with `concurrency=1`
- **THEN** the returned bundle contains `"concurrency": 1`.
