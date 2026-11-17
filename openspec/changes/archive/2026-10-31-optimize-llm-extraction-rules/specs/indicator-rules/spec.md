# indicator-rules (delta)

## ADDED Requirements

### Requirement: Selector resolution supports section-map alias expansion
For `report` rules, the selector resolution process SHALL support alias expansion via the section map capability (`report-section-map`).

If a selector's `section` field equals a canonical section key, the engine SHALL attempt to resolve the section by trying the ordered candidate list (canonical key + aliases) until one matches the parsed report outline. If the `section` field is not a canonical key, the engine SHALL attempt resolution using the raw value only.

#### Scenario: Canonical section key matches an alias in the outline
- **WHEN** a selector uses `section: "财务报表附注"` and the report outline contains `合并财务报表附注`
- **THEN** section resolution succeeds by matching the alias and records the matched outline title in provenance.

### Requirement: Provenance records the matched section title
When a `report` rule resolves via a selector, the system SHALL record the matched outline title (the exact heading text that matched) in the indicator's provenance/source fields so failures and regressions can be diagnosed.

#### Scenario: Matched title is preserved
- **WHEN** section resolution matches an outline heading `主要会计数据和财财务指标`
- **THEN** the returned indicator bundle contains provenance/source text including that exact heading.

