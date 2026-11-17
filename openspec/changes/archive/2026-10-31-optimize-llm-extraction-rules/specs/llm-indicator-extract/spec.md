# llm-indicator-extract (delta)

## ADDED Requirements

### Requirement: LLM extraction prioritizes section-resolved context over broad fallbacks
For `report`-type rules, the system SHALL prioritize using the text of the resolved section(s) as the LLM input context. If a selector expands to multiple candidate section titles via the section map, the engine SHALL select the first matching section in candidate order and SHALL NOT concatenate unrelated sections by default.

#### Scenario: First matching candidate is used
- **WHEN** a selector expands to candidates `[A, B, C]` and the outline contains both `B` and `C`
- **THEN** the engine uses `B` and records that matched title in provenance.

### Requirement: LLM requested indicator list is form-filtered and auditable
When building a single-section LLM request, the system SHALL ensure the `wanted` list excludes form-incompatible rules (per `report_type` gating) and SHALL record the final `wanted` indicator names in provenance for audit/debugging.

#### Scenario: Annual-only indicators are not sent for quarterly extraction
- **WHEN** extraction runs for `form="第一季度报告"` and a rule declares `report_type: "年报"`
- **THEN** that rule is excluded from the LLM request payload and appears in `skipped` with `source_type: "form_filter"`.

