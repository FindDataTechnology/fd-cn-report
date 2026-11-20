# indicator-batch-extract (Delta)

## MODIFIED Requirements

### Requirement: One Pydantic-typed LLM call per section replaces per-individual extractor dispatch

For `report`-type rules, the system SHALL sub-partition the applicable rules by their resolved section. All non-akshare, non-computed rules in a section SHALL be extracted by a single `call_llm_pydantic` call using the section's Pydantic model. The system SHALL NOT dispatch per-indicator Python extractors (`python:table_row`, `python:percent_value`, `python:headcount`) — these extractor types no longer exist. The system SHALL NOT issue more than one LLM call per distinct section.

#### Scenario: One Pydantic call per section

- **WHEN** all `balance_sheet` rules resolve to the `合并资产负债表` section
- **THEN** exactly one `call_llm_pydantic` call is made for that section using `BalanceSheetResult` as the model, returning validated results for all 86 balance sheet indicators.

#### Scenario: Python extractors no longer dispatched

- **WHEN** a rule's `extractor` field is absent or set to `llm`
- **THEN** the rule is handled by the Pydantic-typed LLM call for its section; no Python extractor registry is consulted.

### Requirement: Computed rules evaluate from Pydantic model outputs

`computed`-type rules SHALL evaluate their formulas using base values obtained from the akshare and Pydantic-typed LLM passes of the same call. The system SHALL NOT delegate arithmetic to the LLM. If any input is missing or non-numeric, the system SHALL place the indicator in `unresolved` with a note naming the missing input.

#### Scenario: Ratio computed from Pydantic model outputs

- **WHEN** `不良率` is `computed` from `不良贷款余额 / 贷款和垫款总额 * 100` and both bases were resolved via `BalanceSheetResult`
- **THEN** the system evaluates the formula locally and returns the ratio with `source_type: "computed"`, `extractor: "computed"`.

### Requirement: Cache key includes Pydantic model version hash

The indicator bundle cache SHALL include a hash of the Pydantic model field set for each section in the cache key. When a Pydantic model is updated (field added, removed, or renamed), the cache SHALL be busted and extraction re-run. This is in addition to the existing `rules_hash`.

#### Scenario: Pydantic model update busts cache

- **WHEN** a field is added to `BalanceSheetResult` and `extract_indicators` is called
- **THEN** the cached bundle for that company/year is invalidated (hash mismatch) and extraction re-runs.

### Requirement: Result shape includes a summary DataFrame alongside the legacy dict

The returned bundle SHALL include a new `dataframe: [{"ticker", "year", "indicator", "value", "unit", "source_section", "period"}]` array alongside the existing `indicators` dict. This provides a machine-friendly format without requiring callers to flatten the dict-of-dicts.

#### Scenario: Bundle carries the dataframe array

- **WHEN** `extract_indicators` runs
- **THEN** the returned bundle contains `dataframe`, a list of dicts, each representing one indicator row with the seven standard columns.

## REMOVED Requirements

### Requirement: Pluggable extractors dispatch by name

**Reason**: Replaced by Pydantic-typed LLM extraction. The `python:table_row`, `python:percent_value`, and `python:headcount` extractors are removed. No new Python extractors will be registered — all extraction goes through per-section Pydantic models and the LLM.

**Migration**: Existing `python:table_row` rules in `indicator_rules.json` have their `extractor` field removed (the `module` field determines the Pydantic model). The `indicators_extractors.py` registry and `register()` API are deleted.
