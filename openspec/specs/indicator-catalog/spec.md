# indicator-catalog

## Purpose

Expose the indicator rule set to callers via the `list_indicators` tool. Browse rules grouped by module/subgroup, preview the rules applicable to a specific company, and free-text search by name or alias. The rule set is a JSON file (`indicator_rules.json`) loaded at tool-call time, mirroring the load/resolve pattern of `cninfo_categories.json`.
## Requirements
### Requirement: Browse the indicator rule set
The system SHALL provide a `list_indicators` tool that returns the indicator rule set. With no arguments it SHALL return every rule grouped by `module` (and `subgroup`), each entry carrying `name`, `aliases`, `module`, `subgroup`, `source_type`, `extractor`, `applies_to`, `unit`, and `period_type`. With a `module` argument it SHALL return only that module's rules. The response SHALL include a `count`.

#### Scenario: List all rules
- **WHEN** `list_indicators()` is called with no arguments
- **THEN** the system returns every rule grouped by module, plus a total `count`.

#### Scenario: Filter by module
- **WHEN** `list_indicators(module="balance_sheet")` is called
- **THEN** the system returns only rules whose `module` is `balance_sheet`, with a `count` reflecting that subset.

#### Scenario: Unknown module
- **WHEN** `list_indicators(module="no_such_module")` is called
- **THEN** the system returns `{"error": "unknown module: ...", "available": [<module names>]}`.

### Requirement: Preview rules applicable to a company
The system SHALL accept a `company` argument (ticker or name) to `list_indicators` and return only the rules whose `applies_to` matches that company's profile, so callers can see exactly which indicators will be processed for a given company before retrieval. The response SHALL include the resolved company profile (`industry`, `sub_type`).

#### Scenario: Company-filtered preview
- **WHEN** `list_indicators(company="工商银行")` is called
- **THEN** the system returns only the rules that apply to 工商银行, the resolved `{industry, sub_type}`, and a `count`.

#### Scenario: Company-only indicators excluded for others
- **WHEN** a rule tagged `companies: ["601398"]` is in the rule set and `list_indicators(company="600519")` is called
- **THEN** that rule is absent from the response for 600519.

### Requirement: Search rules by name or alias
The system SHALL accept a `query` argument to `list_indicators` and return the rules whose `name` or `aliases` match the query via normalized substring match.

#### Scenario: Free-text search
- **WHEN** `list_indicators(query="资本")` is called
- **THEN** the system returns every rule whose name or alias contains `资本`, with a `count`.

#### Scenario: No matches
- **WHEN** `list_indicators(query="zzz_nomatch")` is called
- **THEN** the system returns `{"indicators": [], "count": 0}`.

### Requirement: Data-driven rule extensibility
The indicator rule set SHALL be loaded from the rules database at tool-call time (see the `rules-database` capability). Adding, editing, or removing a rule SHALL require only a write to the rules database (via the write API, a migration, or a generator skill) — no Python code change and no server restart beyond the next tool call. `indicator_rules.json` SHALL NOT be consulted at runtime; it is a migration seed only.

#### Scenario: Add a rule by a database write
- **WHEN** a new rule is upserted into the rules database and `list_indicators` is called again
- **THEN** the new rule appears in the response without any code change.

#### Scenario: Rules database is the source of truth
- **THEN** `list_indicators`, `get_indicator`, `extract_indicators`, and the extraction script SHALL all read from the same in-memory rule set loaded from the rules database, so the catalog, lookup, batch, and script never disagree.

### Requirement: Methodology documentation
The system SHALL ship a methodology document (`docs/indicators-methodology.md`) generated from `indicator_rules.json`. For each rule it SHALL record `source_type`, the concrete `selectors[]` chain, `extractor`, `applies_to`, `unit`, and `note`. The document SHALL include a **"Adding a new rule"** section and an **"Adding a new extractor"** section documenting the extension contract. The existing `indicators.md` catalog SHALL remain unchanged.

#### Scenario: Document covers every rule
- **WHEN** the methodology document is read
- **THEN** every rule present in `indicator_rules.json` has an entry stating where its value comes from and how it is processed.

#### Scenario: Document reflects rule edits
- **WHEN** the rule set is edited and the methodology is regenerated
- **THEN** the document's content matches the edited rule set exactly.

