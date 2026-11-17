## ADDED Requirements

### Requirement: Three offering and HK report types are first-class report forms
The system SHALL support three additional report forms selectable via the `form` argument of the extraction entry points, each with a `_FORM_COMPAT_KEY` entry and a `document_type` value used to tag and select its rules:

- `招股说明书` - CN public-offering prospectus (公开募股); `document_type` `招股说明书`; sourced from the CNINFO `首发` category (`category_sf_szsh`).
- `港股全球发售` - HKEX global-offering prospectus (招股章程); `document_type` `港股全球发售`; sourced from HKEX 披露易.
- `港股年度报告` - HKEX annual report; `_FORM_COMPAT_KEY` maps `港股年度报告` to `港股年度报告`; `document_type` `港股年度报告`; sourced from HKEX 披露易.

The `document_type` of each new rule SHALL equal its compat key. No new rule's `document_type` SHALL be a substring match for any CN periodic form's compat key (`年报`, `半年报`, `季报`), and no CN periodic rule's `report_type` SHALL match any new form's compat key, so the new types and the periodic types are mutually disjoint under `_form_compatible`.

#### Scenario: New forms are accepted by the extraction entry points
- **WHEN** `extract_indicators` and `extract_indicators_by_position` are called with `form` set to each of `招股说明书`, `港股全球发售`, `港股年度报告`
- **THEN** the call does not raise `KeyError`/`ValueError`, and the returned bundle's `form` field equals the requested form.

#### Scenario: Form-compat keys cover the new types
- **WHEN** `_FORM_COMPAT_KEY` is read from `indicators_client` and from `report_section_map`
- **THEN** both contain `招股说明书 -> 招股说明书`, `港股全球发售 -> 港股全球发售`, and `港股年度报告 -> 港股年度报告`.

#### Scenario: CN prospectus resolves to the CNINFO 首发 category
- **WHEN** `cninfo_client.resolve_category("招股说明书")` is called
- **THEN** it returns `category_sf_szsh` (the `首发` category under the `融资` group of `cninfo_categories.json`).

#### Scenario: HK prospectus and annual filings are fetchable
- **WHEN** `hk_stock_client.get_hk_prospectus_filing(stock_code)` and `hk_stock_client.get_hk_annual_report_filing(stock_code, year)` are called
- **THEN** each returns a filing record (title + `pdf_url`) from HKEX 披露易, or `None` when no matching filing exists.

### Requirement: Prospectus and HK section maps
`docs/report_section_map.json` SHALL contain a top-level form entry for each new type's compat key (`招股说明书`, `港股全球发售`, `港股年度报告`), mapping canonical section names to non-empty alias lists. The prospectus maps (`招股说明书`, `港股全球发售`) SHALL cover at least: 发行概况, 风险因素, 发行人基本情况, 业务概况, 募集资金运用, 财务会计信息, 管理层讨论与分析, 股本及股东, 董事监事高级管理人员. The HK annual map (`港股年度报告`) SHALL cover the annual-report canonical sections with Traditional-Chinese and English aliases (綜合收益表, 財務狀況表, 綜合現金流量表, 管理層討論與分析). `report_section_map.candidates(form, section)` SHALL resolve a canonical section to its alias list for the new forms.

#### Scenario: Prospectus section resolves to aliases
- **WHEN** `report_section_map.candidates("招股说明书", "募集资金运用")` is called
- **THEN** it returns a non-empty ordered list beginning with `募集资金运用` and including at least one alias.

#### Scenario: HK annual section resolves with a Traditional alias
- **WHEN** `report_section_map.candidates("港股年度报告", "财务报表")` is called
- **THEN** the returned list includes a Traditional-Chinese alias such as `財務報表`.

### Requirement: Baseline LLM-rule coverage per offering/HK type
For each implemented offering/HK `document_type`, the system SHALL persist a baseline set of LLM rules in `llm_rules` (via the `fd-cnreport-pdf-llm-rules-creator` skill or the rules write API), each carrying `indicator`, `instruction`, `position`, `document_type`, and `module`. The baseline indicator sets are:

- `招股说明书`: 发行价, 发行股数, 募集资金总额, 募集资金净额, 发行费用, 发行后总股本, 募集资金投向, 补充流动资金, 营业收入, 净利润, 总资产, 净资产, 经营活动现金流, 主要风险因素, 主营业务, 控股股东, 实际控制人, 主要股东持股, 董事人数.
- `港股年度报告`: 营业收入, 经营利润, 净利润, 毛利, 总资产, 净资产, 经营活动现金流, 每股股息, 主要股东持股, 董事人数.

The `港股全球发售` baseline set (发行价, 发售股数, 募集资金总额, 募集资金净额, 超额配售权, 募集资金用途, 营业收入, 净利润, 总资产, 净资产, 主要风险因素, 主营业务, 基石投资者, 主要股东, 董事人数) is the target for a follow-up change: its type plumbing, section map, and `get_hk_prospectus_filing` fetch path are already in place, but the LLM rules are not yet generated (blocked on sourcing a recent HK global-offering prospectus PDF).

Prospectus-specific indicators (e.g. 发行价, 募集资金净额, 募集资金投向, 主要风险因素, 基石投资者) MAY use `module` values outside the existing `balance_sheet | income_statement | cashflow | financial_ratio` set (e.g. `offering`, `use_of_proceeds`, `risk_factors`, `corporate`); the `module` field is a free string and the extractor groups rules by `(module, subgroup)`.

#### Scenario: Every baseline indicator has an LLM rule for implemented types
- **WHEN** the rules database is queried for `llm_rules` grouped by `document_type` for each of `招股说明书`, `港股年度报告`
- **THEN** every indicator in that type's baseline set is present (by `indicator` name or alias).

#### Scenario: Prospectus rules are disjoint from periodic-form extraction
- **WHEN** `_form_compatible` is evaluated for a rule with `document_type="招股说明书"` against `form="年度报告"`
- **THEN** it returns false, so the rule is skipped for annual extraction.
