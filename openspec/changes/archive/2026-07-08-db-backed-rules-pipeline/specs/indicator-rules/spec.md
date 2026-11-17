## MODIFIED Requirements

### Requirement: Rule structure maps an indicator to a source location and extractor
The system SHALL load an indicator rule set from the rules database (see the `rules-database` capability). Each rule SHALL define: `name`, `aliases`, `module`, `subgroup`, `applies_to`, `source_type` (`akshare` | `report` | `computed` | `external`), and an extraction specification. For `report` rules the spec SHALL be an ordered `selectors[]` chain (each entry an optional `company` filter + a `section` selector + optional `fallback` flag) plus an `extractor` field. The `extractor` field for `report` rules SHALL be `"llm"` or omitted (defaults to `"llm"`), or SHALL resolve to a script rule — a row in the `script_rules` table whose `extract_rule` names a registered extractor (see the `script-indicator-extract` capability). For `computed` rules the spec SHALL be `{formula, inputs}`; for `external` rules the spec SHALL carry no `selectors[]` and no `extractor`. `indicator_rules.json` is retained only as a migration seed; it is no longer the runtime source of truth.

#### Scenario: report rule with a selector chain
- **WHEN** a `report` rule for 资本充足率 declares `selectors: [{company: ["601398"], section: "三、资本充足率分析"}, {section: "资本充足率"}, {section: "风险管理", fallback: true}]`
- **THEN** for 工商银行 the engine tries `三、资本充足率分析` first; for any other bank it tries `资本充足率` first, then `风险管理`.

#### Scenario: Script rule dispatches via the registry
- **WHEN** a rule for 利息收入 has a matching `script_rules` row with `extract_rule: "table_row"`
- **THEN** the engine dispatches to the registered `table_row` extractor with the section text + rule, returns `{value, unit, note}`, and makes no LLM call.

#### Scenario: LLM rule dispatches via the LLM batch path
- **WHEN** a `report` rule has no matching `script_rules` row
- **THEN** the engine dispatches it through the LLM batch path with `extractor: "llm"`.

#### Scenario: computed rule with formula and inputs
- **WHEN** a `computed` rule declares `{formula: "不良贷款余额 / 贷款和垫款总额 * 100", inputs: ["不良贷款余额", "贷款和垫款总额"]}`
- **THEN** the engine evaluates the formula locally once both inputs are resolved, and never sends arithmetic to the LLM.

#### Scenario: external rule carries no selectors
- **WHEN** a rule for `PE-TTM` declares `source_type: "external"` and `report_type: "实时"`
- **THEN** the rule carries no `selectors[]` and no `extractor`, and the engine does not attempt to resolve a section or dispatch an extractor for it.

## ADDED Requirements

### Requirement: Rules database is the runtime source of truth
The system SHALL load rules from the rules database at runtime. `indicator_rules.json` SHALL serve only as a migration seed (consumed by `scripts/migrate_rules_to_db.py`). `list_indicators`, `get_indicator`, `extract_indicators`, and the extraction script SHALL all read from the same in-memory rule set loaded from the rules database, so the catalog, lookup, batch, and script never disagree. The in-memory rule set SHALL be rebuilt from the database when its cache is invalidated by a write.

#### Scenario: Database is the source of truth
- **WHEN** rules are inserted or updated in the rules database
- **THEN** the next `load_rules()` call reflects them, and `indicator_rules.json` is not consulted at runtime.
