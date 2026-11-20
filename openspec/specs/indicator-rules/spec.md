# indicator-rules

## Purpose

Define the structure and behavior of the indicator rule set: how rules map an indicator to a source location and extractor, how companies are profiled for applicability, how rules are filtered per company, how pluggable extractors dispatch by name, and how sections are resolved by walking the `selectors[]` chain.

## Requirements

### Requirement: Rule structure maps an indicator to a source location and extractor
The system SHALL load an indicator rule set from `indicator_rules.json`. Each rule SHALL define: `name`, `aliases`, `module`, `subgroup`, `applies_to`, `source_type` (`akshare` | `report` | `computed` | `external`), and an extraction specification. For `akshare` rules the spec SHALL be `{statement, field}`; for `report` rules it SHALL be an ordered `selectors[]` chain (each entry an optional `company` filter + a `section` selector + optional `fallback` flag) plus an `extractor` (`"llm"` or `"python:<name>"`) and optional `schema_hint`; for `computed` rules it SHALL be `{formula, inputs}`; for `external` rules the spec SHALL carry no `selectors[]` and no `extractor` (the indicator is sourced from realtime/market data, not the report PDF). Each rule MAY carry `unit`, `period_type`, `direction`, `note`, and a `report_type` field recording which periodic report types contain the indicator (e.g. `年报/半年报/季报`, `年报/半年报`, `年报`, `实时`). The `report_type` field SHALL be used by `extract_indicators_by_position` to filter indicators by form compatibility: an indicator is compatible with a form if the form's compatibility key (`年报` for 年度报告, `半年报` for 半年度报告, `季报` for 第一季度报告/第三季度报告) is a substring of `report_type`. Rules without a `report_type` field SHALL be treated as `年报/半年报/季报` (broadly applicable) for filtering purposes.

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

#### Scenario: report_type filters an annual-only indicator out of quarterly
- **WHEN** `extract_indicators_by_position(form="第一季度报告")` is called and a rule for `分红金额` declares `report_type: "年报"`
- **THEN** `季报` is not a substring of `年报`, so the rule is routed to `skipped` with `source_type: "form_filter"` and is not attempted against the Q1 PDF.

#### Scenario: missing report_type defaults to broadly applicable
- **WHEN** a hand-authored banking rule carries no `report_type` field and `extract_indicators_by_position(form="第一季度报告")` is called
- **THEN** the rule is treated as `年报/半年报/季报`, `季报` is a substring, and the rule is attempted (not skipped) for the Q1 form.

### Requirement: Company profiling classifies a company for applicability
The system SHALL provide `profile_company(stock_code, name)` returning `{industry, sub_type}`. For banks, `sub_type` SHALL be one of {国有大行, 股份制, 城商行, 农商行}, resolved by a curated ticker→sub-type lookup with a name-keyword heuristic fallback. For non-bank companies (not in the bank ticker lookup AND whose name has no `银行` keyword), the system SHALL return `{industry: <non-bank>, sub_type: null}` so that universal rules (`applies_to.industry: "*"`) apply while bank-scoped rules (`applies_to.industry: "bank"`) are excluded. The profile SHALL be exposed by `list_indicators(company=...)` so callers can verify classification before extraction.

#### Scenario: Major bank classified by ticker lookup
- **WHEN** `profile_company("601398")` is called
- **THEN** it returns `{industry: "bank", sub_type: "国有大行"}`.

#### Scenario: Unknown bank falls back to name heuristic
- **WHEN** `profile_company("601xxx", name="某某城市商业银行")` is called and the ticker is not in the lookup
- **THEN** it returns `{industry: "bank", sub_type: "城商行"}` via the name keyword.

#### Scenario: Non-bank company profiles without sub_type
- **WHEN** `profile_company("600519", name="贵州茅台")` is called
- **THEN** it returns `{industry: <non-bank>, sub_type: null}`, so universal rules apply and bank-scoped rules are excluded.

### Requirement: Applicability filtering selects rules per company
The system SHALL provide `applicable_rules(company)` returning the subset of rules whose `applies_to` matches the company's profile. A rule applies iff `industry` matches AND (`sub_types` is empty/`["*"]` OR the company's `sub_type` is listed) AND the company is not in `exclude_companies` AND (`companies` is `["*"]`/empty OR the company is listed). `get_indicator`, `extract_indicators`, and the extraction script SHALL only attempt applicable rules, so different companies run different rule subsets.

#### Scenario: Sub-type-scoped rule
- **WHEN** a rule declares `applies_to: {industry: "bank", sub_types: ["国有大行"]}` and the company is a 城商行
- **THEN** `applicable_rules` excludes that rule for the 城商行.

#### Scenario: Company-only rule
- **WHEN** a rule declares `applies_to: {industry: "bank", companies: ["601398"]}`
- **THEN** `applicable_rules` includes it only for 601398 and excludes it for every other company.

#### Scenario: Exclude override
- **WHEN** a rule declares `applies_to: {industry: "bank", sub_types: ["*"], exclude_companies: ["601398"]}`
- **THEN** `applicable_rules` excludes it for 601398 and includes it for every other bank.

### Requirement: Section resolution walks the selector chain
The engine SHALL resolve a `report` rule's section by walking its `selectors[]` chain via `resolve_selector` (exact → normalized leading-keyword substring → regex) against the parsed outline, trying company-filtered selectors first. When no selector matches AND the rule's module is a statement module (`balance_sheet` / `income_statement` / `cashflow`), the engine SHALL fall back to searching the raw report text for the canonical statement title (`合并资产负债表` / `合并利润表` / `合并现金流量表`, then the un-prefixed `资产负债表` / `利润表` / `现金流量表`, then the bank quarterly variant `合并及公司资产负债表` / `合并及公司利润表` / `合并及公司现金流量表`), slicing from the title line to the next statement title or top-level numbered heading. The fallback SHALL only activate when outline resolution returns nothing, so reports whose outlines contain statement titles (annual, semi-annual) are unaffected.

#### Scenario: Company-specific selector wins
- **WHEN** the first `selectors[]` entry has `company: ["601398"]` and the target is 601398 and its section is in the TOC
- **THEN** that selector is used and later entries are not tried.

#### Scenario: Fallback to default selector
- **WHEN** the company-specific selector's section is not in the TOC but the next (default) entry's section is
- **THEN** the default selector is used.

#### Scenario: No selector hits
- **WHEN** no `selectors[]` entry matches a section in the parsed TOC
- **THEN** the indicator is listed in `missing` with the tried selectors recorded, and no extractor runs.

#### Scenario: Annual report resolves via outline
- **WHEN** a `balance_sheet` rule is resolved against the 工商银行 2023 年度报告 (outline contains `合并资产负债表`)
- **THEN** the outline-based `resolve_statement` succeeds and the body-text fallback is not activated.

#### Scenario: Quarterly report resolves via body-text fallback
- **WHEN** a `cashflow` rule is resolved against the 工商银行 2023 Q1 report (outline lacks `合并现金流量表`)
- **THEN** the body-text fallback finds `合并及公司现金流量表` in the raw text (via the `现金流量表` substring), slices the cashflow section, and returns it as the section body.

### Requirement: Rule set is maintainable from a position CSV
The system SHALL treat `docs/indicators_position.csv` as the maintained human-editable source of the indicator rule set. A migration step (`scripts/migrate_indicators_csv.py`) SHALL convert each CSV row (`indicator`, `indicator_cn`, `section_en`, `section_cn`, `report_type`) into a rule in `indicator_rules.json` per a deterministic mapping: `indicator` → `name`; `indicator_cn` → alias; `section_en`/`section_cn` → `module`/`subgroup`/`selectors[]`; `report_type` → `source_type` classification + `period_type`. The migration SHALL be idempotent (re-running produces the same JSON), SHALL preserve rules already present in the JSON that did not originate from the CSV, and SHALL annotate overlapping rules (same `name`) with the CSV's `report_type` and `indicator_cn` alias without discarding their richer existing `selectors[]`/`applies_to`/`direction`. Adding or editing an indicator SHALL require only an edit to the CSV followed by re-running the migration — no Python code change.

#### Scenario: CSV row becomes a rule
- **WHEN** the migration runs over a CSV row `{indicator: "资产总计", indicator_cn: "Total Assets", section_en: "Balance Sheet - Assets", section_cn: "资产负债表 — 一、资产", report_type: "年报/半年报/季报"}`
- **THEN** the resulting rule has `name: "资产总计"`, an alias `"Total Assets"`, `module: "balance_sheet"`, `subgroup: "资产负债表 — 一、资产"`, `source_type: "report"`, a `selectors[]` entry targeting the section, `report_type: "年报/半年报/季报"`, and universal `applies_to`.

#### Scenario: Overlap preserves the richer existing rule
- **WHEN** the migration encounters a CSV row whose `indicator` matches an existing rule's `name`
- **THEN** the existing rule's `selectors[]`, `applies_to`, and `direction` are preserved; only `report_type` and the `indicator_cn` alias are added/updated.

#### Scenario: Idempotent re-run
- **WHEN** the migration is run twice in a row over an unchanged CSV
- **THEN** the second run produces no diff in `indicator_rules.json`.

#### Scenario: CSV edit refreshes the rules
- **WHEN** a new indicator row is appended to `docs/indicators_position.csv` and the migration is re-run
- **THEN** the new rule appears in `indicator_rules.json` and is reachable from `list_indicators` on the next tool call, with no Python code change.

### Requirement: report_type classifies source_type as report or external
The migration SHALL derive each rule's `source_type` from its CSV `report_type`: values containing `年报`/`半年报`/`季报`/`年度` SHALL yield `source_type: "report"`; the value `实时` (realtime market data, sections `Market Data (External)` / `Fund Holdings (External)`) SHALL yield `source_type: "external"`. Extraction paths (`extract_indicators`, `get_indicator`, `extract_indicators_by_position`) SHALL honor the classification: an `external` rule SHALL NOT trigger a PDF fetch, akshare call, or LLM call, and SHALL be reported as `unresolved`/`skipped` with a note.

#### Scenario: Periodic report_type classified as report
- **WHEN** a CSV row has `report_type: "年报/半年报/季报"`
- **THEN** the resulting rule has `source_type: "report"` and is extracted from the report PDF.

#### Scenario: Realtime report_type classified as external
- **WHEN** a CSV row has `report_type: "实时"`
- **THEN** the resulting rule has `source_type: "external"`, carries no `selectors[]`, and is skipped during report extraction.

### Requirement: Rules database is the runtime source of truth
The system SHALL load rules from the rules database at runtime. `indicator_rules.json` SHALL serve only as a migration seed (consumed by `scripts/migrate_rules_to_db.py`). `list_indicators`, `get_indicator`, `extract_indicators`, and the extraction script SHALL all read from the same in-memory rule set loaded from the rules database, so the catalog, lookup, batch, and script never disagree. The in-memory rule set SHALL be rebuilt from the database when its cache is invalidated by a write.

#### Scenario: Database is the source of truth
- **WHEN** rules are inserted or updated in the rules database
- **THEN** the next `load_rules()` call reflects them, and `indicator_rules.json` is not consulted at runtime.

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
