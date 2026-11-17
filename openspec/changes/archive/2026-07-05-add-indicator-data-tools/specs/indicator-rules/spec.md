## ADDED Requirements

### Requirement: Rule structure maps an indicator to a source location and extractor
The system SHALL load an indicator rule set from `indicator_rules.json`. Each rule SHALL define: `name`, `aliases`, `module`, `subgroup`, `applies_to`, `source_type` (`akshare` | `report` | `computed`), and an extraction specification. For `akshare` rules the spec SHALL be `{statement, field}`; for `report` rules it SHALL be an ordered `selectors[]` chain (each entry an optional `company` filter + a `section` selector + optional `fallback` flag) plus an `extractor` (`"llm"` or `"python:<name>"`) and optional `schema_hint`; for `computed` rules it SHALL be `{formula, inputs}`. Each rule MAY carry `unit`, `period_type`, `direction`, `note`.

#### Scenario: report rule with a selector chain
- **WHEN** a `report` rule for 资本充足率 declares `selectors: [{company: ["601398"], section: "三、资本充足率分析"}, {section: "资本充足率"}, {section: "风险管理", fallback: true}]`
- **THEN** for 工商银行 the engine tries `三、资本充足率分析` first; for any other bank it tries `资本充足率` first, then `风险管理`.

#### Scenario: computed rule with formula and inputs
- **WHEN** a `computed` rule declares `{formula: "不良贷款余额 / 贷款和垫款总额 * 100", inputs: ["不良贷款余额", "贷款和垫款总额"]}`
- **THEN** the engine evaluates the formula locally once both inputs are resolved, and never sends arithmetic to the LLM.

### Requirement: Company profiling classifies a company for applicability
The system SHALL provide `profile_company(stock_code, name)` returning `{industry, sub_type}`. For banks, `sub_type` SHALL be one of {国有大行, 股份制, 城商行, 农商行}, resolved by a curated ticker→sub-type lookup with a name-keyword heuristic fallback. The profile SHALL be exposed by `list_indicators(company=...)` so callers can verify classification before extraction.

#### Scenario: Major bank classified by ticker lookup
- **WHEN** `profile_company("601398")` is called
- **THEN** it returns `{industry: "bank", sub_type: "国有大行"}`.

#### Scenario: Unknown bank falls back to name heuristic
- **WHEN** `profile_company("601xxx", name="某某城市商业银行")` is called and the ticker is not in the lookup
- **THEN** it returns `{industry: "bank", sub_type: "城商行"}` via the name keyword.

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

### Requirement: Pluggable extractors dispatch by name
The system SHALL maintain an extractor registry in `indicators_extractors.py` mapping names to Python functions `(section_text, rule, period) -> {value, unit, note}`, with a `register(name, fn)` API. A rule's `extractor: "python:<name>"` SHALL dispatch to the registered function. A rule's `extractor: "llm"` SHALL route through the existing `ai_extract` path. A rule's `extractor: "auto"` (or omitted) SHALL resolve to `computed` for computed rules, the akshare fetch for akshare rules, and `llm` for report rules unless a `python:` extractor is named. Adding a new Python extractor SHALL require only adding a function and calling `register` — no engine change.

#### Scenario: python extractor dispatch
- **WHEN** a rule declares `extractor: "python:regex_amount"` and the registry contains `regex_amount`
- **THEN** the engine calls `regex_amount(section_text, rule, period)` and returns its result with `extractor: "python:regex_amount"`, making no LLM call.

#### Scenario: Unknown python extractor name
- **WHEN** a rule declares `extractor: "python:no_such"` and no function is registered under that name
- **THEN** the rule's result is `{value: null, note: "unknown extractor: python:no_such"}` and the indicator is listed in `unresolved`.

#### Scenario: Registering a new extractor
- **WHEN** the user adds a function and calls `register("my_parser", fn)` in `indicators_extractors.py`, then sets `extractor: "python:my_parser"` on a rule
- **THEN** the engine dispatches to `fn` for that rule with no other code change.

### Requirement: Section resolution walks the selector chain
For `report` rules, the system SHALL resolve the section by walking `selectors[]` in order: for each entry whose `company` filter matches the target (or has no `company` filter), attempt `resolve_selector` (exact → regex) on the parsed outline; the first hit is used. If no entry hits, the indicator SHALL be listed in `missing`. The system SHALL fetch the matched section's text through the report cache.

#### Scenario: Company-specific selector wins
- **WHEN** the first `selectors[]` entry has `company: ["601398"]` and the target is 601398 and its section is in the TOC
- **THEN** that selector is used and later entries are not tried.

#### Scenario: Fallback to default selector
- **WHEN** the company-specific selector's section is not in the TOC but the next (default) entry's section is
- **THEN** the default selector is used.

#### Scenario: No selector hits
- **WHEN** no `selectors[]` entry matches a section in the parsed TOC
- **THEN** the indicator is listed in `missing` with the tried selectors recorded, and no extractor runs.
