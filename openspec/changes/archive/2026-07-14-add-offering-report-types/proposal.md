## Why

`fd-cn-report` only extracts indicators from the four CN periodic report forms
(年度报告 / 半年度报告 / 第一季度报告 / 第三季度报告). Offering documents - the CN
招股说明书 (公开募股) and the HKEX 全球发售 (招股章程) - and HK annual reports are out
of reach, even though their disclosure structure (发行概况, 历史财务数据, 募集资金运用,
风险因素, 主要股东, 董事及高管) maps cleanly onto the existing section + rule pipeline.
The data is already fetchable - CNINFO exposes 招股说明书 via its `首发` category
(`category_sf_szsh`) and HKEX via 披露易 - so what is missing is (a) report-type
definitions + section maps, (b) LLM rules for these types, and (c) removal of the
hard-coded "annual-report / 2023" assumptions that block them. This change mirrors the
existing CN annual-report logic to add these "process" (offering) report types, with the
LLM rules as the central deliverable.

## What Changes

- Add three new report types, each a `form` selector + `_FORM_COMPAT_KEY` entry +
  `document_type` value:
  - `招股说明书` - CN 公开募股 prospectus; source CNINFO `首发` / `category_sf_szsh`.
  - `港股全球发售` - HKEX global-offering prospectus (招股章程); source HKEX 披露易.
  - `港股年度报告` - HKEX annual report (compat key `港股年度报告`); source HKEX 披露易
    (annual-report fetch already exists in `hk_stock_client`).
- Add prospectus / HK section maps to `docs/report_section_map.json` (发行概况, 风险因素,
  业务概况, 募集资金运用, 历史财务数据, 财务报表, 主要股东, 董事监事及高管, …) with
  Simplified / Traditional / English aliases; extend `_FORM_COMPAT_KEY` in both
  `indicators_client.py` and `report_section_map.py`.
- **Generate LLM rules** (`llm_rules` rows with `document_type` = the new types) for each
  type via the existing `fd-cnreport-pdf-llm-rules-creator` skill, covering a baseline
  indicator set per type (发行价 / 发行股数 / 募集资金净额 / 募集资金投向 / 风险因素 /
  历史营收·利润·总资产 / 主要股东 / 董事高管 …). **This is the core deliverable.**
- Generalize the hard-coded annual-report assumptions in the extraction pipeline:
  parameterize the `_llm_extract_section` system prompt (drop the literal `"2023"` and the
  "Chinese annual-report text" framing), relax the `_resolve_via_akshare` Dec-31 year-end
  target, and extend the heading / statement matchers to HK + prospectus outline styles.
- Apply `_form_compatible` filtering in the plain `extract_indicators` path (today only the
  CSV-driven `extract_indicators_by_position` path filters by form), so prospectus rules do
  not run against annual reports and vice versa. **BREAKING** for callers that relied on the
  plain path ignoring `form`.
- Extend clients: `cninfo_client` resolves `form="招股说明书"` -> `category_sf_szsh` and
  recognizes 招股说明书 titles in `_form_from_title`; `hk_stock_client` gains a
  prospectus-filing lookup (HKEX 全球发售 / 招股章程) alongside the existing annual-report
  fetch.
- Include `form` in `make_report_id` so an annual report and a prospectus for the same
  company + year no longer collide in `report_documents`.

## Capabilities

### New Capabilities

- `offering-report-types`: Defines the 招股说明书 / 港股全球发售 / 港股年度报告 report
  types - `form` names, `_FORM_COMPAT_KEY` entries, `document_type` values, CNINFO / HKEX
  source mapping, the prospectus / HK section-map structure, and the baseline indicator set
  each type's LLM rules must cover.

### Modified Capabilities

- `llm-indicator-extract`: The supported form set is no longer capped at the four CN
  periodic forms; it is extensible and includes the three new types. `_form_compatible`
  filtering SHALL apply in the plain `extract_indicators` path, not only the CSV-driven
  path. The LLM system prompt SHALL be parameterized by period and SHALL NOT assume an
  annual report.

## Impact

- **Code**: `indicators_client.py` (`_FORM_COMPAT_KEY`, `_form_compatible` call site,
  `_llm_extract_section` prompt, `_resolve_via_akshare`), `report_section_map.py`
  (`_FORM_COMPAT_KEY`), `docs/report_section_map.json` (3 new form maps),
  `cninfo_client.py` (`首发` resolution, `_form_from_title`), `hk_stock_client.py`
  (prospectus filing lookup), `cnreport_database.py` (`make_report_id` includes `form`).
- **Data**: new `llm_rules` rows for the three types, persisted to the rules DB and the
  generator skill's `scripts/` dir for inspection / version control.
- **Specs**: new `offering-report-types`; modified `llm-indicator-extract`.
- **Tests**: existing "exactly four forms" assertions in `test_llm_indicator_extract.py` /
  `test_cnreport.py` must be updated; add form-compat, section-map, and rule-coverage tests
  for the new types.
- **Dependencies**: none new. Reuses the existing generator skills (`rules-generator-skills`)
  and the rules database (`rules-database`).
