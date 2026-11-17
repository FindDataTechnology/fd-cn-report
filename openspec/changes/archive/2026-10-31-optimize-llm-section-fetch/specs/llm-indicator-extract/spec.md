## MODIFIED Requirements

### Requirement: LLM extraction is one call per section per module with a JSON records schema
For a set of `report`-type rules assigned to one section, the extractor SHALL make one LLM call per `(module, subgroup)` group — **or reuse the records already cached for that group by the section cache** (`llm_section_cache`). The call SHALL be issued through `call_llm_pydantic` with the subgroup's Pydantic model (`indicators_models.model_for_subgroup`) as the response schema, and SHALL send a system instruction built by `_build_llm_system_prompt` plus a user payload containing `period`, a field description per **missing** indicator, and the section `text`. Every `report`-type rule in a resolved section SHALL be included in the LLM call — there is no longer a split between `llm_rules` and `python_rules` within a section. A group whose indicators are already fully present in the cache SHALL NOT trigger an LLM call. The `extractor_mode: "python"` argument SHALL place all report rules in `unresolved` with note `skipped: llm extractor in python mode` (since no Python extractors exist).

The section cache is keyed by `(pdf_url, section_key, period, rules_hash)`, where `rules_hash` is the stable hash over **all** rules in that `(module, subgroup)` (`_subgroup_rules_hash`). The wanted set is deliberately **not** part of the key: the cache stores the union of records ever fetched for the group, and the caller derives the missing subset locally. A change in section text (`pdf_url`/`section_key`/`period`) or in the rule set therefore produces a fresh LLM call; a change in the requested subset alone does not.

#### Scenario: LLM receives the expected prompt shape
- **WHEN** the LLM extractor runs for a section with two report rules and no section-cache hit
- **THEN** `call_llm_pydantic` is invoked exactly once for that group, its `user` argument parses as JSON containing `period`, the field descriptions for both indicators, and `text`.

#### Scenario: Records are mapped back to rule names
- **WHEN** the LLM returns an instance whose `model_dump()` holds the two indicator names
- **THEN** the bundle's `indicators` map contains those two names with the returned values and `extractor: "llm"`, and the records are persisted to the section cache (metadata fields `section`/`page`/`source` excluded).

#### Scenario: Full cache hit avoids a second LLM call
- **WHEN** a previous run cached records for `(pdf_url, section_key, period, rules_hash)` and the current run requests the same group with the same rules hash
- **THEN** `call_llm_pydantic` is not invoked, the cached values are returned with note `llm-section-cache`, and `section_cache_reuse` counts them.

#### Scenario: Partial hit queries only the missing indicators
- **WHEN** the section cache holds records for `{A, B}` and the current run requests `{A, B, C}`
- **THEN** `call_llm_pydantic` is invoked once with a model containing only `C`, `A` and `B` are served from the cache, and `put()` merges `C` into the stored superset so the entry grows to `{A, B, C}`.

#### Scenario: Rules-hash change invalidates the cache
- **WHEN** `indicator_rules.json` is edited so `_subgroup_rules_hash` returns a new value
- **THEN** the next run does not reuse the entries written under the previous hash and makes a fresh LLM call.

#### Scenario: All report rules in a section go to LLM
- **WHEN** a section contains 5 `balance_sheet` rules and 3 `report_section` rules
- **THEN** the system makes 2 LLM calls (one per module), each including all rules of that module as fields in the Pydantic schema.

#### Scenario: Python mode skips all report rules
- **WHEN** `extractor_mode="python"` is passed and a `report` rule has `extractor: "llm"`
- **THEN** that rule is listed in `unresolved` with note `skipped: llm extractor in python mode` and no LLM call is made.

### Requirement: Result bundle mirrors the position-extraction script output
`extract_indicators_by_position(..., extractor="llm", form=<form>)` SHALL return a bundle with the header fields `{stock_code, company_name, year, form, pdf_url, cached, csv_path, extractor_mode, section_cache_reuse}` and the lists `indicators`, `missing`, `unresolved`, `skipped`. Each `indicators` entry SHALL carry `{value, unit, source_type, extractor, source, period, provenance}`. The `skipped` array SHALL contain `{indicator, source_type, note}` entries. The `section_cache_reuse` field SHALL be an integer count of indicator records served from the section cache (zero when no section cache hit occurred); it is independent of `cached`, which indicates a full bundle hit.

#### Scenario: Bundle shape on a successful LLM extraction
- **WHEN** extraction runs with the LLM mocked to return valid records
- **THEN** the returned bundle contains every header field, every `indicators` entry carries the seven fields, `extractor_mode` equals the requested mode, and `section_cache_reuse` is an integer.

#### Scenario: Form is appended to the output stem for non-annual forms
- **WHEN** the script writes outputs for `form="半年度报告"`
- **THEN** the output stem is `<stock>_<year>_半年度报告` (not `<stock>_<year>`), matching the CLI's stem rule.

#### Scenario: section_cache_reuse reflects cached records
- **WHEN** a run reuses N indicator records from the section cache
- **THEN** `bundle["section_cache_reuse"]` equals N.
