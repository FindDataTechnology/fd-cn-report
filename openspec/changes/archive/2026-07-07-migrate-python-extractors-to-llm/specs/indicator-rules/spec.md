## MODIFIED Requirements

### Requirement: Rule structure maps an indicator to a source location and extractor
The system SHALL load an indicator rule set from `indicator_rules.json`. Each rule SHALL define: `name`, `aliases`, `module`, `subgroup`, `applies_to`, `source_type` (`akshare` | `report` | `computed` | `external`), and an extraction specification. For `report` rules the spec SHALL be an ordered `selectors[]` chain (each entry an optional `company` filter + a `section` selector + optional `fallback` flag) plus an `extractor` field. The `extractor` field for `report` rules SHALL be `"llm"` or omitted (defaults to `"llm"`). The `python:<name>` extractor type is REMOVED — rules that previously declared `python:table_row`, `python:percent_value`, or `python:headcount` SHALL declare `extractor: "llm"`. The `indicators_extractors.py` module and its `register()` / `get()` API are deleted. For `computed` rules the spec SHALL be `{formula, inputs}`; for `external` rules the spec SHALL carry no `selectors[]` and no `extractor`.

#### Scenario: Former python:table_row rule is now llm
- **WHEN** a rule for `利息收入` previously declared `extractor: "python:table_row"` with `source.selectors: [{section: "利润表"}]`
- **THEN** the rule now declares `extractor: "llm"` (or omits the field), and the engine dispatches it through the LLM batch path with no Python extractor call.

#### Scenario: No python extractor dispatch path exists
- **WHEN** the engine processes a `report` rule
- **THEN** it SHALL NOT attempt to import `indicators_extractors` or call any registered Python function — the `python:` branch is removed from `_run_extractor`.
