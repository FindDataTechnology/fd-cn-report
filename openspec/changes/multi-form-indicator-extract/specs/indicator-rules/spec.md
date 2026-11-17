## MODIFIED Requirements

### Requirement: Rule structure maps an indicator to a source location and extractor
The system SHALL load an indicator rule set from `indicator_rules.json`. Each rule SHALL define: `name`, `aliases`, `module`, `subgroup`, `applies_to`, `source_type` (`akshare` | `report` | `computed` | `external`), and an extraction specification. For `akshare` rules the spec SHALL be `{statement, field}`; for `report` rules it SHALL be an ordered `selectors[]` chain (each entry an optional `company` filter + a `section` selector + optional `fallback` flag) plus an `extractor` (`"llm"` or `"python:<name>"`) and optional `schema_hint`; for `computed` rules it SHALL be `{formula, inputs}`; for `external` rules the spec SHALL carry no `selectors[]` and no `extractor` (the indicator is sourced from realtime/market data, not the report PDF). Each rule MAY carry `unit`, `period_type`, `direction`, `note`, and a `report_type` field recording which periodic report types contain the indicator (e.g. `年报/半年报/季报`, `年报/半年报`, `年报`, `实时`). The `report_type` field SHALL be used by `extract_indicators_by_position` to filter indicators by form compatibility: an indicator is compatible with a form if the form's compatibility key (`年报` for 年度报告, `半年报` for 半年度报告, `季报` for 第一季度报告/第三季度报告) is a substring of `report_type`. Rules without a `report_type` field SHALL be treated as `年报/半年报/季报` (broadly applicable) for filtering purposes.

#### Scenario: report rule with a selector chain
- **WHEN** a `report` rule for 资本充足率 declares `selectors: [{company: ["601398"], section: "三、资本充足率分析"}, {section: "资本充足率"}, {section: "风险管理", fallback: true}]`
- **THEN** for 工商银行 the engine tries `三、资本充足率分析` first; for any other bank it tries `资本充足率` first, then `风险管理`.

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

### Requirement: Section resolution walks selectors with body-text fallback
The engine SHALL resolve a `report` rule's section by walking its `selectors[]` chain via `resolve_selector` (exact → normalized leading-keyword substring → regex) against the parsed outline, trying company-filtered selectors first. When no selector matches AND the rule's module is a statement module (`balance_sheet` / `income_statement` / `cashflow`), the engine SHALL fall back to searching the raw report text for the canonical statement title (`合并资产负债表` / `合并利润表` / `合并现金流量表`, then the un-prefixed `资产负债表` / `利润表` / `现金流量表`, then the bank quarterly variant `合并及公司资产负债表` / `合并及公司利润表` / `合并及公司现金流量表`), slicing from the title line to the next statement title or top-level numbered heading. The fallback SHALL only activate when outline resolution returns nothing, so reports whose outlines contain statement titles (annual, semi-annual) are unaffected.

#### Scenario: Annual report resolves via outline
- **WHEN** a `balance_sheet` rule is resolved against the 工商银行 2023 年度报告 (outline contains `合并资产负债表`)
- **THEN** the outline-based `resolve_statement` succeeds and the body-text fallback is not activated.

#### Scenario: Quarterly report resolves via body-text fallback
- **WHEN** a `cashflow` rule is resolved against the 工商银行 2023 Q1 report (outline lacks `合并现金流量表`)
- **THEN** the body-text fallback finds `合并及公司现金流量表` in the raw text (via the `现金流量表` substring), slices the cashflow section, and returns it as the section body.
