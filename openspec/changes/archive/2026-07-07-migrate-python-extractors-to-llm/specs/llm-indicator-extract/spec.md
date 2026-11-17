## MODIFIED Requirements

### Requirement: LLM extraction is one call per section per module with a JSON records schema
For a set of `report`-type rules assigned to one section, the extractor SHALL make a single LLM call per module. The call SHALL send a system instruction requesting ONLY a JSON object matching the module's Pydantic model schema, and a user payload containing `period`, `wanted` (each entry carrying `indicator` and `unit`), and the section `text`. All `report`-type rules in a resolved section SHALL be included in the LLM call — there is no longer a split between `llm_rules` and `python_rules` within a section. The `extractor_mode: "python"` argument SHALL place all report rules in `unresolved` with note `skipped: llm extractor in python mode` (since no Python extractors exist).

#### Scenario: All report rules in a section go to LLM
- **WHEN** a section contains 5 `balance_sheet` rules and 3 `report_section` rules
- **THEN** the system makes 2 LLM calls (one per module), each including all rules of that module as fields in the Pydantic schema.

#### Scenario: Python mode skips all report rules
- **WHEN** `extractor_mode="python"` is passed and a `report` rule has `extractor: "llm"`
- **THEN** that rule is listed in `unresolved` with note `skipped: llm extractor in python mode` and no LLM call is made.
