## ADDED Requirements

### Requirement: Five project-scoped generator skills
The system SHALL provide 5 skills under `.claude/skills/`, each invokable via the skill-creator workflow: `fd-cnreport-llm-rules-creator`, `fd-cnreport-pdf-llm-rules-creator`, `fd-cnreport-pdf-scripts-creator`, `fd-cnreport-pdf-scripts-by-type-creator`, and `fd-cnreport-pdf-full-scripts-creator`. Each skill SHALL ship a `SKILL.md` and a Python generator script in its own `scripts/` directory.

#### Scenario: Skill directory layout
- **WHEN** a generator skill is installed
- **THEN** `.claude/skills/<skill>/SKILL.md` and `.claude/skills/<skill>/scripts/<generator>.py` both exist.

### Requirement: Pydantic-validated structured output
Every generator script SHALL define a pydantic model for its output (an LLM rule or a script rule) and SHALL validate the LLM response against it before persisting. Invalid output SHALL be rejected and SHALL NOT be written to the database.

#### Scenario: LLM returns malformed rule
- **WHEN** the LLM returns a rule missing `document_type`
- **THEN** pydantic validation raises and no rule is persisted.

#### Scenario: Valid rule persisted
- **WHEN** the LLM returns a well-formed rule
- **THEN** it is validated, upserted into the rules database, and saved to the skill's `scripts/` dir.

### Requirement: LLM rules from a document section (skill 1)
`fd-cnreport-llm-rules-creator` SHALL accept a piece of a document and generate LLM rules (`indicator`, `instruction`, `position`, `document_type`) via the LLM, validate with pydantic, and persist to the rules database and the skill's `scripts/` dir.

#### Scenario: Generate rules from a section excerpt
- **WHEN** a section text excerpt is passed to the skill
- **THEN** it produces one or more validated LLM rules upserted into `llm_rules`.

### Requirement: LLM rules per chapter from a whole PDF (skill 2)
`fd-cnreport-pdf-llm-rules-creator` SHALL accept a whole PDF, split it by outline into chapters, and generate LLM rules per chapter via the LLM, validate with pydantic, and persist to the rules database and the skill's `scripts/` dir.

#### Scenario: Whole PDF split by outline
- **WHEN** a PDF is passed to the skill
- **THEN** it is split into chapters by the parsed outline and LLM rules are generated for each chapter.

### Requirement: Script rules from DB rules (skill 3)
`fd-cnreport-pdf-scripts-creator` SHALL read a single rule/document's rules from the rules database, generate script rules (`indicator`, `extract_rule`, `position`, `document_type`) for them via the LLM, validate with pydantic, and persist to the rules database and the skill's `scripts/` dir.

#### Scenario: Generate script rules for one document's rules
- **WHEN** a document's rules are read from the DB
- **THEN** a script rule is generated and upserted into `script_rules` for each target indicator.

### Requirement: Script rules by document_type (skill 4)
`fd-cnreport-pdf-scripts-by-type-creator` SHALL read all rules for a given `document_type` from the rules database, generate script rules per target indicator, validate with pydantic, and persist to the rules database and the skill's `scripts/` dir.

#### Scenario: Generate script rules for a document_type
- **WHEN** a `document_type` is passed to the skill
- **THEN** script rules are generated for every target indicator of that type and upserted into `script_rules`.

### Requirement: Full extraction script by document_type (skill 5)
`fd-cnreport-pdf-full-scripts-creator` SHALL generate a full end-to-end extraction script for a given `document_type`, drawing on the LLM and script rules in the database, and save it to the rules database and the skill's `scripts/` dir.

#### Scenario: Generate a full extraction script
- **WHEN** a `document_type` is passed to the skill
- **THEN** a runnable extraction script covering all of that type's indicators is generated and saved.

### Requirement: Persistence to rules database and skill scripts dir
Each generator skill SHALL persist its output both to the rules database (via the write API) and to its own `scripts/` directory (as a serialized artifact). The database is the runtime source of truth; the `scripts/` dir copy is for inspection and version control.

#### Scenario: Output written to both locations
- **WHEN** a generator skill produces rules
- **THEN** they are upserted into the rules database AND written under `.claude/skills/<skill>/scripts/`.
