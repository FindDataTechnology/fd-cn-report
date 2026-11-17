## MODIFIED Requirements

### Requirement: Data-driven rule extensibility
The indicator rule set SHALL be loaded from the rules database at tool-call time (see the `rules-database` capability). Adding, editing, or removing a rule SHALL require only a write to the rules database (via the write API, a migration, or a generator skill) — no Python code change and no server restart beyond the next tool call. `indicator_rules.json` SHALL NOT be consulted at runtime; it is a migration seed only.

#### Scenario: Add a rule by a database write
- **WHEN** a new rule is upserted into the rules database and `list_indicators` is called again
- **THEN** the new rule appears in the response without any code change.

#### Scenario: Rules database is the source of truth
- **THEN** `list_indicators`, `get_indicator`, `extract_indicators`, and the extraction script SHALL all read from the same in-memory rule set loaded from the rules database, so the catalog, lookup, batch, and script never disagree.
