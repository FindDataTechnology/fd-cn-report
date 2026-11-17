## 1. Report-type definitions and compat keys

- [x] 1.1 Add `招股说明书 -> 招股说明书`, `港股全球发售 -> 港股全球发售`, `港股年度报告 -> 港股年度报告` to `_FORM_COMPAT_KEY` in `indicators_client.py`
- [x] 1.2 Add the same three entries to `_FORM_COMPAT_KEY` in `report_section_map.py`
- [x] 1.3 Confirm the three new `document_type` values (`招股说明书`, `港股全球发售`, `港股年度报告`) are accepted by `extract_indicators` / `extract_indicators_by_position` via `form` without raising

## 2. Prospectus and HK section maps

- [x] 2.1 Add a `招股说明书` form entry to `docs/report_section_map.json` with canonical sections (发行概况, 风险因素, 发行人基本情况, 业务概况, 募集资金运用, 财务会计信息, 管理层讨论与分析, 股本及股东, 董事监事高级管理人员) + Simplified aliases
- [x] 2.2 Add a `港股全球发售` form entry mirroring the prospectus sections with Traditional-Chinese + English aliases (招股章程, 募集資金用途, 風險因素, 業務概況)
- [x] 2.3 Add a `港股年度报告` form entry reusing the annual-report canonical sections with Traditional + English statement aliases (綜合收益表, 財務狀況表, 綜合現金流量表, 管理層討論與分析)
- [x] 2.4 Verify `report_section_map.candidates("招股说明书", "募集资金运用")` and `candidates("港股年度报告", "财务报表")` return non-empty alias lists; run `report_section_map._validate_section_map` over the file

## 3. Source clients

- [x] 3.1 In `cninfo_client.py`, make `resolve_category("招股说明书")` return `category_sf_szsh` (map the `首发` category under `融资` to the `招股说明书` form)
- [x] 3.2 Extend `cninfo_client._form_from_title` to recognize 招股说明书 / 首发 announcement titles as `招股说明书`
- [x] 3.3 Add `hk_stock_client.get_hk_prospectus_filing(stock_code, year=None)` that searches HKEX 披露易 for 全球发售 / 招股章程 filings, paralleling `get_hk_annual_report_filing`
- [x] 3.4 Confirm `get_hk_annual_report_filing` already serves `form="港股年度报告"`; wire the HK forms through `list_hk_filings` title search

## 4. Pipeline generalization (drop hard-coded annual assumptions)

- [x] 4.1 Parameterize the `_llm_extract_section` system prompt by the requested period; remove the literal `"2023"` and the "Chinese annual-report text" framing (no document-type assertion)
- [x] 4.2 Relax the `_resolve_via_akshare` Dec-31 `target` to derive the fiscal year-end when available, falling back to Dec-31 only for CN periodic forms
- [x] 4.3 Extend the heading matchers (`_HEADING_RE` / `_HEADING_LOOSE_RE`) and statement matchers (`STATEMENT_TITLES` / `STATEMENT_MATCHERS`) in `cnreport_tools.py` with HK + prospectus patterns (第X部/Part/Section; 綜合收益表/財務狀況表/綜合現金流量表; 招股章程 section titles)
- [x] 4.4 Include `form` in `cnreport_database.make_report_id` (`sha1(source|company|year|form)`) so annual and prospectus documents for the same company + year do not collide

## 5. Form-compat filtering in the plain extract path (BREAKING)

- [x] 5.1 Hoist the `_form_compatible(rule, form)` filter into the shared rule-selection step used by both `extract_indicators` and `extract_indicators_by_position`
- [x] 5.2 Place form-incompatible rules in `skipped` with `source_type: "form_filter"` and note `not in <form>` in the plain path, matching the CSV path
- [x] 5.3 Re-run `test_cnreport.py` and `test_llm_indicator_extract.py`; update any assertion that relied on the plain path ignoring `form`; confirm the annual-report path is unaffected (existing rules carry `年报/半年报/季报`)

## 6. Generate LLM rules for the three new types (core deliverable)

- [~] 6.1 Select one representative PDF per type (CN 招股说明书, HK 招股章程 / 全球发售, HK annual report) and stage it for the generator — CN 招股说明书 + HK annual done; 港股全球发售 prospectus PDF DEFERRED to follow-up change (no recent equity-IPO source available)
- [x] 6.2 Run `fd-cnreport-pdf-llm-rules-creator` with `--document-type 招股说明书` over the CN prospectus PDF; upsert rules into `llm_rules`
- [ ] 6.3 Run `fd-cnreport-pdf-llm-rules-creator` with `--document-type 港股全球发售` over the HK prospectus PDF; upsert rules into `llm_rules` — BLOCKED: HKEX client fixed (annual fetch works) but no recent equity-IPO prospectus PDF locatable (akshare/HKEX new-listings unavailable; documentType=19000 returns CBBC listing docs, not equity prospectuses). Pipeline ready; needs a recent-IPO prospectus URL.
- [x] 6.4 Run `fd-cnreport-pdf-llm-rules-creator` with `--document-type 港股年度报告` over the HK annual report PDF; upsert rules into `llm_rules`
- [x] 6.5 Verify each type's generated rules cover its baseline indicator set (see `offering-report-types` spec); iterate with `fd-cnreport-llm-rules-creator` on missing indicators from section excerpts — 招股说明书 (13/13) + 港股年度报告 (8/9) verified; 港股全球发售 coverage DEFERRED (rules not yet generated)
- [x] 6.6 Confirm the serialized rule copies landed in each skill's `scripts/` dir for inspection / version control

## 7. Tests and validation

- [x] 7.1 Update the "exactly four forms" / `_FORM_COMPAT_KEY` assertions in `test_llm_indicator_extract.py` and `test_cnreport.py` to the extensible seven-form set
- [x] 7.2 Add a test asserting `_form_compatible` is false for a `招股说明书` rule against `form="年度报告"` and true against `form="招股说明书"`
- [x] 7.3 Add a test asserting `report_section_map.candidates` resolves prospectus + HK sections to aliases
- [x] 7.4 Add a coverage test asserting every baseline indicator for each new `document_type` has an `llm_rules` row (mocked DB fixture)
- [x] 7.5 Add a no-network test asserting the `_llm_extract_section` prompt references the requested period and contains no hard-coded year
- [x] 7.6 Run `openspec validate add-offering-report-types` and the full `fd-cn-report` test suite (`pytest`, `selfcheck.py`); ensure green
