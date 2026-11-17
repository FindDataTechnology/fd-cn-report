## ADDED Requirements

### Requirement: Script-rule dispatch via a named-extractor registry
The system SHALL provide an extractor registry that maps an `extract_rule` name to a callable `(section_text, rule, period) -> {value, unit, note}`. The registry SHALL be populated at import time with built-in extractors (at minimum `regex_amount`, `percent_value`, `table_row`, `headcount`). `extract_indicators` and `get_indicator` SHALL dispatch rules whose `extractor` resolves to a script rule by looking up `extract_rule` in the registry.

#### Scenario: Script rule runs the registered extractor
- **WHEN** a script rule declares `extract_rule: "regex_amount"` and the section text is fetched
- **THEN** the engine calls the registered `regex_amount` function with the section text and rule, returns `{value, unit, note}`, and makes no LLM call.

#### Scenario: Unknown extract_rule
- **WHEN** a script rule declares `extract_rule: "no_such_extractor"`
- **THEN** the engine returns `{value: null, note: "unknown extractor: no_such_extractor"}` and does not raise.

### Requirement: Script rules resolved from the rules database
The system SHALL resolve script rules by reading the `script_rules` table for the requested `indicator` and `document_type`. A rule's `extractor` field SHALL resolve to a script rule when a matching `script_rules` row exists; otherwise the existing `llm` / `computed` / `akshare` dispatch SHALL apply unchanged.

#### Scenario: Rule with a matching script rule
- **WHEN** a rule for 利息收入 has a `script_rules` row with `extract_rule: "table_row"`
- **THEN** the engine dispatches via the registry instead of the LLM path.

#### Scenario: Rule without a script rule falls back to LLM
- **WHEN** a rule for 资本充足率 has no `script_rules` row
- **THEN** the engine dispatches via the LLM batch path as before.

### Requirement: Result shape matches LLM extraction
A script-rule extraction SHALL return the same result shape as an LLM extraction: `{indicator, value, unit, period, note, extractor, source_type}`. The `extractor` field SHALL identify the script extractor used (e.g. `script:regex_amount`).

#### Scenario: Script result merges into the bundle
- **WHEN** a batch extraction mixes LLM and script rules
- **THEN** both produce entries in the `indicators` list with the same field set, distinguishable only by `extractor`.
