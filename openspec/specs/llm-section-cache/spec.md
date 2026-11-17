# llm-section-cache Specification

## Purpose
TBD - created by archiving change optimize-llm-section-fetch. Update Purpose after archive.

## Requirements

### Requirement: Persistent section-level LLM response cache
The system SHALL persist the indicator records extracted from one `(module, subgroup)` group of a section to a section-level cache (`llm_section_cache`). The cache SHALL be keyed by a stable hash of `(pdf_url, section_key, period, rules_hash)`, where `rules_hash` is the subgroup-level hash over **all** rules of that group (`_subgroup_rules_hash`) — the wanted set is deliberately excluded from the key so that a section accumulates records across callers as a growing superset instead of fragmenting per subset. The cache SHALL live on disk under `<CNREPORT_CACHE_DIR>/llm_sections/` (the same directory tree used by `report_cache`), and SHALL be written atomically (temp file, then `os.replace`). Cache lookups SHALL occur before any HTTP call to the LLM, and only when the caller supplies both `pdf_url` and `section_key`. The cache SHALL be opt-out via an environment variable (`LLM_SECTION_CACHE=off`); the default SHALL be enabled.

#### Scenario: Cache hit avoids LLM call
- **WHEN** the same section (same `pdf_url`, `section_key`, `period`, and subgroup `rules_hash`) is extracted twice across two `extract_indicators_by_position` runs
- **THEN** the second run makes zero calls to `call_llm_pydantic` and returns the same indicator values as the first run, with `section_cache_reuse` counting the reused records.

#### Scenario: Cache miss triggers exactly one LLM call
- **WHEN** the group is queried for the first time
- **THEN** exactly one `call_llm_pydantic` call is made for the missing indicators and the response is persisted to the cache.

#### Scenario: Changing the wanted set alone does not miss the cache
- **WHEN** a previous run cached `{A, B, C}` for a section and a later run requests `{A, B, D}`
- **THEN** the cached entry is reused for `A` and `B`, `call_llm_pydantic` is invoked once with a model containing only `D`, and `put()` merges `D` into the stored superset so it grows to `{A, B, C, D}`.

#### Scenario: Changing the rule set does miss the cache
- **WHEN** `indicator_rules.json` is edited so `_subgroup_rules_hash` returns a new value
- **THEN** the previous cache entry is not reused and a fresh LLM call is made. Old cache files MAY remain on disk; they are not read under the new hash and are not auto-pruned by this requirement.

#### Scenario: Cache write failure does not break extraction
- **WHEN** the cache directory is not writable
- **THEN** the extractor returns the LLM response as if the cache were absent, and the failure is logged at debug level.

#### Scenario: Cache is disabled via env var
- **WHEN** `LLM_SECTION_CACHE=off` is set
- **THEN** no cache files are read or written and the extractor behaves identically to the pre-cache implementation.

### Requirement: Single-indicator resolution reuses the section cache
When `get_indicator` is called for a `report`-source rule, the engine SHALL consult the section cache (via `_llm_extract_section`, which receives `pdf_url` and `section_key`) before invoking the LLM. A cache hit SHALL return the cached value with note `llm-section-cache`; a miss SHALL fall through to one LLM call for that rule and write the result back to the cache.

#### Scenario: get_indicator for a previously-extracted rule does not call LLM
- **WHEN** `extract_indicators_by_position` has already extracted that rule from the same PDF and section, and `get_indicator` is then called for it
- **THEN** no `call_llm_pydantic` call is made and the returned value matches the cached one.

#### Scenario: get_indicator for a not-yet-cached rule falls through to LLM
- **WHEN** `get_indicator` is called for a rule that has no entry in the section cache
- **THEN** `_llm_extract_section` is called with the section's text and the single rule, the response is cached, and the value is returned.

### Requirement: Bundle reports partial cache reuse
The extraction bundle SHALL carry an integer `section_cache_reuse` field equal to the number of indicator records served from the section cache in that run (zero when no section cache hit occurred). It SHALL be reported independently of `cached`, which indicates a full bundle hit.

#### Scenario: section_cache_reuse reflects cached records
- **WHEN** a run reuses N indicator records from the section cache
- **THEN** `bundle["section_cache_reuse"]` equals N.
