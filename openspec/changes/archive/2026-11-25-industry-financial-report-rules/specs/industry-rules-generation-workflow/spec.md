## ADDED Requirements

### Requirement: Workflow to generate LLM rules per industry/document_type
The system SHALL define an operator workflow to generate LLM rules for a target `(industry, document_type)` using existing generator skills.

The workflow SHALL include:

- Selecting `(industry, company_type, report_kind)` and computing `document_type`
- Preparing representative inputs (PDF or excerpt) for that industry/document_type
- Generating LLM rules for the target indicators for that industry/document_type
- Validating and persisting the generated rules

#### Scenario: Generate LLM rules for a new industry/document_type
- **WHEN** an operator runs the LLM rule generation process for a target industry/document_type
- **THEN** the system produces validated LLM rules persisted under that `document_type`

### Requirement: Workflow to derive script rules from LLM rules per industry/document_type
The system SHALL define an operator workflow to derive script rules from existing LLM rules for a target `(industry, document_type)` using existing generator skills.

#### Scenario: Derive script rules after LLM rules exist
- **WHEN** validated LLM rules exist for an industry/document_type’s target indicators
- **THEN** the system generates validated script rules for those indicators and persists them under the same `document_type`

### Requirement: Iterative maintenance loop
The system SHALL define an iterative loop for improving extraction quality by updating rules rather than requiring code changes for each new variation.

#### Scenario: Update rules after a failure on a new report template
- **WHEN** extraction fails for one or more indicators on a new report template for a supported industry/document_type
- **THEN** an operator updates or regenerates the relevant LLM rules and/or script rules for that `document_type` and re-validates coverage

