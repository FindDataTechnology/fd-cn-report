## Why

`extract_indicators_by_position` only fetches `form="年度报告"`, so the 278 indicators the CSV marks as available in 季报 and the 298 available in 半年报 are unreachable from any periodic report other than the annual. Verification against real reports confirmed the gap: quarterly reports resolve **0%** of report-rules because their outline parser never captures `合并资产负债表`/`合并利润表`/`合并现金流量表` as section titles (they appear as body text under `四、季度财务报表`), and semi-annual reports resolve fewer indicators than annual for non-banks. The CSV also carried 32 exact-duplicate rows and 6 non-standard `report_type` values that broke form-based filtering.

## What Changes

- Fix `docs/indicators_position.csv` data quality: remove 32 exact-duplicate rows (353→321), normalize `report_type` values (`季报/半年报/年报`→`年报/半年报/季报`, `年度`→`年报`). Re-migrate into `indicator_rules.json` (321 rules, already synced).
- Add a `form` parameter to `extract_indicators_by_position` accepting `年度报告` (default), `半年度报告`, `第一季度报告`, `第三季度报告`. The chosen form flows through to `extract_indicators` → `_build_ctx` → `cninfo_client.query_announcements(form=…)`.
- Add `report_type` filtering: when a form is specified, indicators whose CSV `report_type` does not include that form are routed to `skipped` (not attempted). E.g. `分红金额` (年报-only) is skipped for 季报; `前五大客户收入占比` (年报-only) is skipped for 半年报. This prevents 40+ guaranteed-miss resolution attempts per quarterly run.
- Add a body-text statement fallback in `_resolve_section`: when the outline does not contain a statement title (`合并资产负债表`/`合并利润表`/`合并现金流量表`), search the raw report text directly and slice the section from the title line to the next statement or next top-level heading. This makes statement line items resolvable in quarterly reports (Q1/Q3) where the outline only captures `一、主要财务数据` / `二、股东信息` / `三、其他提醒事项` / `四、季度财务报表`.
- Extend `scripts/extract_indicators_by_position.py` with a `--form` flag mirroring the tool.
- Test extraction with two companies (工商银行 601398, 贵州茅台 600519) across all four forms (年报/半年报/Q1/Q3), verifying that statement indicators resolve in quarterly reports and form-incompatible indicators are skipped.

## Capabilities

### New Capabilities
- `multi-form-indicator-extract`: Extends `extract_indicators_by_position` to accept a `form` parameter (年度报告/半年度报告/第一季度报告/第三季度报告), filter indicators by the CSV's `report_type` availability for that form, and resolve statement sections via body-text fallback when the outline lacks statement titles (the quarterly-report case).

### Modified Capabilities
- `indicator-position-extract`: the `extract_indicators_by_position` tool gains a `form` argument (default `年度报告`); the result bundle records the `form` used; indicators unavailable in the chosen form are listed in `skipped` with `reason: "not in {form}"` rather than attempted.
- `indicator-position-script`: `scripts/extract_indicators_by_position.py` gains a `--form` flag; output JSON/CSV record the form and the form-skipped rows.
- `indicator-rules`: CSV `report_type` column is the filter source; the migration already preserves it on each rule. No schema change, but the engine now reads `rule.report_type` to decide form compatibility.

## Impact

- **Data**: `docs/indicators_position.csv` 353→321 rows (32 exact duplicates removed, 6 `report_type` values normalized). `indicator_rules.json` re-migrated (321 rules, in sync).
- **Code**: `indicators_client.py` — `extract_indicators_by_position` gains `form` param + `report_type` filter + body-text statement fallback in `_resolve_section`; `extract_indicators` gains a `form` passthrough (already accepts `form`). `scripts/extract_indicators_by_position.py` — `--form` flag. `cnreport_tools.py` — new `find_statement_in_text` helper for the body-text fallback (reused by `_resolve_section`).
- **APIs**: `extract_indicators_by_position` gains optional `form` arg (additive, default preserves existing behavior). No breaking change.
- **Dependencies**: none new.
- **Tests**: extend `test_cnreport.py` with form-filtering, body-text fallback, and quarterly-resolution cases. Add a 2-company × 4-form integration test using cached reports (offline).
- **Docs**: README indicator section updated to mention `form` support; `docs/indicators-methodology.md` regenerated.
