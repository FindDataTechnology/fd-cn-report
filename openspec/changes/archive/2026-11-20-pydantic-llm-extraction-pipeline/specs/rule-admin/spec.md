# rule-admin

## Purpose

Provide a CLI tool `extract_rules` for listing, adding, removing, editing, and inspecting indicator rules. The CLI operates on `indicator_rules.json` directly and validates edits against the Pydantic models.

## ADDED Requirements

### Requirement: CLI lists rules with optional module filter

The system SHALL provide `extract_rules list [--module <name>]` that prints a table of rules with columns `name | module | extractor | source_type | selectors`. When `--module` is provided, only rules for that module are shown. Output is plain text formatted with aligned columns.

#### Scenario: List all rules

- **WHEN** `extract_rules list` runs
- **THEN** output contains every rule in `indicator_rules.json`, one per line, with aligned columns.

#### Scenario: Filter by module

- **WHEN** `extract_rules list --module balance_sheet` runs
- **THEN** output contains only rules whose `module` is `balance_sheet`.

### Requirement: CLI adds a new rule with schema validation

`extract_rules add <name> --module <name> --selectors "<title1>,<title2>"` SHALL add a new rule to `indicator_rules.json`. The command SHALL validate that the module has a corresponding Pydantic model (i.e., the indicator name exists as a field in the model or is a new field being introduced). When a company-scoped rule is needed, the `--company <code>` flag SHALL set `applies_to.companies`.

#### Scenario: Add a balance sheet indicator

- **WHEN** `extract_rules add 应收利息 --module balance_sheet --selectors "合并资产负债表"` runs
- **THEN** `indicator_rules.json` contains a new `report`-type rule with `name: "应收利息"`, `module: "balance_sheet"`, and `selectors[{section: "合并资产负债表"}]`.

#### Scenario: Add with company scope

- **WHEN** `extract_rules add 专项指标 --module report_section --selectors "特定章节" --company 601398` runs
- **THEN** the new rule has `applies_to.companies: ["601398"]`.

#### Scenario: Unknown module is rejected

- **WHEN** `extract_rules add 某指标 --module no_such_module --selectors "某章节"` runs
- **THEN** the command prints an error and exits non-zero; `indicator_rules.json` is unchanged.

### Requirement: CLI removes a rule

`extract_rules rm <name>` SHALL remove the rule with matching `name` from `indicator_rules.json`. If no rule matches, the command SHALL print an error and exit non-zero.

#### Scenario: Remove existing rule

- **WHEN** `extract_rules rm 应收利息` runs after adding it
- **THEN** `indicator_rules.json` no longer contains a rule named `应收利息`.

### Requirement: CLI edits a rule's fields

`extract_rules edit <name> --field value --value <new>` SHALL update a rule field. Supported fields: `selectors` (replace the selector chain), `module` (change module), `applies_to` (replace applicability), `aliases` (replace alias list). Changes SHALL be validated: module changes SHALL verify the new module has a corresponding Pydantic model.

#### Scenario: Change a rule's section selector

- **WHEN** `extract_rules edit 资产总计 --field selectors --value "合并资产负债表,资产负债表"` runs
- **THEN** the rule's `selectors` array is replaced with the two new entries.

### Requirement: CLI previews the JSON Schema for a module

`extract_rules json-schema --module balance_sheet` SHALL print the JSON Schema that would be used for LLM structured output for the specified module's Pydantic model. Output is formatted JSON.

#### Scenario: Preview balance sheet schema

- **WHEN** `extract_rules json-schema --module balance_sheet` runs
- **THEN** output is valid JSON containing property names, types, and descriptions matching the `BalanceSheetResult` model's fields.

### Requirement: CLI shows the current effective rule count and module distribution

`extract_rules stats` SHALL print a summary table: total rules, per-module counts, per-extractor counts, and source_type distribution.

#### Scenario: Stats output

- **WHEN** `extract_rules stats` runs
- **THEN** output includes at least three sections: total count, per-module breakdown, per-extractor breakdown, all with numeric counts.
