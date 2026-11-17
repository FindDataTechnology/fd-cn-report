## ADDED Requirements

### Requirement: Rules persisted in SQLite with an env-configurable path
The system SHALL persist indicator rules in the project's SQLite database (`daas.db` by default) using SQLAlchemy. The database location SHALL be configurable via the `DAAS_DATABASE_URL` environment variable (extending the existing pattern in `cnreport_database.py`), defaulting to `sqlite:///daas.db`. The rules tables SHALL be created on startup if absent and SHALL coexist with the existing `report_documents` / `report_sections` / `es_index_meta` tables in the same database file.

#### Scenario: Default database path
- **WHEN** `DAAS_DATABASE_URL` is not set
- **THEN** rules are stored in `sqlite:///daas.db` alongside the existing report tables.

#### Scenario: Custom database path via env
- **WHEN** `DAAS_DATABASE_URL=sqlite:////tmp/test.db` is set
- **THEN** rules are read from and written to `/tmp/test.db`, isolating tests from the production DB.

### Requirement: Two rule types — LLM rules and script rules
The system SHALL store two distinct rule types in separate tables. An LLM rule (`llm_rules` table) SHALL carry `indicator`, `instruction`, `position`, `document_type`, plus the metadata the pipeline requires (`module`, `applies_to`, `unit`, `period_type`, `value_range`, `source_type`, `source`). A script rule (`script_rules` table) SHALL carry `indicator`, `extract_rule`, `position`, `document_type`, plus the same shared metadata. Each rule SHALL have a unique `id` and a uniqueness constraint on `(indicator, document_type)` within its table. All non-script rules (including `akshare` / `computed` / `external` source types) SHALL be stored in `llm_rules` with their `source_type` preserved.

#### Scenario: LLM rule row
- **WHEN** an LLM rule for 资本充足率 is stored
- **THEN** the row has `indicator="资本充足率"`, a non-empty `instruction`, a `position`, `document_type`, `module="financial_ratio"`, and `source_type="report"`.

#### Scenario: Script rule row
- **WHEN** a script rule for 利息收入 is stored
- **THEN** the row has `indicator="利息收入"`, an `extract_rule` referencing a registered extractor, a `position`, and `document_type`.

#### Scenario: Duplicate indicator within a document_type rejected
- **WHEN** two LLM rules with the same `indicator` and `document_type` are inserted
- **THEN** the second insert SHALL fail with a uniqueness violation.

### Requirement: One-shot migration from indicator_rules.json
The system SHALL provide a migration script (`scripts/migrate_rules_to_db.py`) that seeds the `llm_rules` table from `indicator_rules.json`. The mapping SHALL be: `name` → `indicator`; `note` + `aliases` + `source` description → `instruction`; `source.selectors` → `position`; `report_type` → `document_type`; `module` / `applies_to` / `unit` / `period_type` / `value_range` / `source_type` / `source` carried through unchanged. The migration SHALL be idempotent (re-running inserts no duplicates and updates no rows unless the JSON changed). `script_rules` SHALL start empty — no script rules exist in the JSON.

#### Scenario: First migration seeds all rules
- **WHEN** the migration runs against `indicator_rules.json` (321 rules) on an empty DB
- **THEN** 321 rows are inserted into `llm_rules` and 0 rows into `script_rules`.

#### Scenario: Re-running migration is a no-op
- **WHEN** the migration runs twice over an unchanged JSON
- **THEN** the second run inserts 0 rows and updates 0 rows.

### Requirement: Read API for the extraction pipeline
The system SHALL provide a read API returning rules as the dict shapes the existing pipeline already expects: `load_rules()` SHALL return `{"rules": [...]}` sourced from the `llm_rules` table (mapping the DB `indicator` column to the in-memory `name` field), and `applicable_rules(company)` SHALL filter by `applies_to` against the company profile. The Pydantic model registry in `indicators_models` SHALL be rebuildable from DB rows. Reads SHALL be cached in-process and the cache SHALL be invalidated on any write.

#### Scenario: Pipeline reads rules from DB
- **WHEN** `extract_indicators` calls `load_rules()`
- **THEN** it receives rules sourced from the `llm_rules` table, not from `indicator_rules.json`.

#### Scenario: Applicability filtering still works
- **WHEN** `applicable_rules("601398")` is called
- **THEN** it returns only rules whose `applies_to` matches 工商银行, identical to the pre-migration behavior.

### Requirement: Write API for generator skills
The system SHALL provide a write API for the generator skills to persist rules: `upsert_llm_rule(rule)` and `upsert_script_rule(rule)` SHALL insert-or-update by `(indicator, document_type)`. Each upsert SHALL validate the rule against a pydantic model before persisting and SHALL invalidate the read cache so the next `load_rules()` reflects the change.

#### Scenario: Skill inserts a new LLM rule
- **WHEN** a generator skill calls `upsert_llm_rule({indicator, instruction, position, document_type, ...})`
- **THEN** the row is inserted and the next `load_rules()` call includes it.

#### Scenario: Skill updates an existing script rule
- **WHEN** a generator skill upserts a script rule whose `(indicator, document_type)` already exists
- **THEN** the existing row is updated with the new `extract_rule` and `position`, and no duplicate is created.

#### Scenario: Invalid rule rejected
- **WHEN** an upsert receives a rule missing `indicator` or `document_type`
- **THEN** pydantic validation SHALL raise and no row is written.
