## ADDED Requirements

### Requirement: Declared indicator set per industry/document_type
For each `(industry, document_type)` pair considered supported, the system SHALL maintain a declared set of target indicators that MUST be extractable for that pair.

#### Scenario: Declaring indicators for a new industry/document_type
- **WHEN** an operator introduces a new industry/document_type for support
- **THEN** they provide a target indicator list for that industry/document_type to serve as the minimum coverage baseline

### Requirement: LLM rule coverage gate for support
The system SHALL treat an industry/document_type as “LLM-rule-ready” only if LLM rules exist for every declared target indicator for that industry/document_type.

#### Scenario: Missing LLM rules blocks readiness
- **WHEN** at least one declared target indicator has no corresponding LLM rule for the industry/document_type
- **THEN** the industry/document_type is not considered LLM-rule-ready

### Requirement: Script rule coverage gate for support
The system SHALL treat an industry/document_type as “script-rule-ready” only if script rules exist for every declared target indicator for that industry/document_type.

#### Scenario: Missing script rules blocks readiness
- **WHEN** at least one declared target indicator has no corresponding script rule for the industry/document_type
- **THEN** the industry/document_type is not considered script-rule-ready

### Requirement: Minimal validation requirements for rules
The system SHALL enforce minimal validation requirements such that persisted rules include required fields:

- LLM rules MUST include `indicator`, `instruction`, `position`, and `document_type`
- Script rules MUST include `indicator`, `extract_rule`, `position`, and `document_type`

#### Scenario: Invalid rule is rejected
- **WHEN** the generator produces a rule missing a required field for its rule type
- **THEN** validation fails and the rule is not persisted as “ready” for coverage gates

### Requirement: Support status derived from coverage and validation
The system SHALL consider an industry/document_type “supported” only if it is both LLM-rule-ready and script-rule-ready, and all required fields pass validation.

#### Scenario: Support status becomes true after rule completion
- **WHEN** all target indicators for an industry/document_type have validated LLM rules and validated script rules
- **THEN** the system marks the industry/document_type as supported

