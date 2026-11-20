## Context

`extract_indicators_by_position` currently hardcodes `form="年度报告"` in its call to `extract_indicators`. The position CSV (`docs/indicators_position.csv`) already records which report types each indicator appears in (`report_type` column: `年报/半年报/季报`, `年报/半年报`, `年报`, `实时`), but the engine never reads this field for form compatibility — it tries every rule against the annual report.

Verification against real cached reports for two test companies (工商银行 601398, 贵州茅台 600519) across four forms (年度报告/半年度报告/第一季度报告/第三季度报告, FY2023) confirmed two concrete blockers:

1. **Quarterly reports resolve 0% of report-rules.** The outline parser (`cnreport_tools.parse_outline`) only captures numbered headings (`一、`, `（一）`, `1.`). Quarterly reports embed `合并资产负债表` / `合并利润表` / `合并现金流量表` as standalone title lines under `四、季度财务报表`, so they never enter the outline. `resolve_statement` → `resolve_selector` finds nothing.

2. **No form filtering.** The engine attempts all 289 report-rules regardless of form, so a quarterly run tries `分红金额` (年报-only), `净利差` (年报/半年报-only), `员工人数` (年报/半年报/季报 but in HR section absent from Q1/Q3) — all guaranteed misses, polluting `missing`/`unresolved` and wasting LLM calls.

The CSV itself had 32 exact-duplicate rows and 6 non-standard `report_type` values (`季报/半年报/年报`, `年度`) — already fixed (321 rows, migrated).

## Goals / Non-Goals

**Goals:**
- `extract_indicators_by_position` accepts `form` ∈ {年度报告, 半年度报告, 第一季度报告, 第三季度报告} and fetches that form from CNINFO.
- Indicators whose `report_type` doesn't include the chosen form are skipped (listed in `skipped` with a reason), not attempted.
- Statement line items (balance sheet / income statement / cashflow modules) resolve in quarterly reports via a body-text fallback when the outline lacks statement titles.
- Two-company × four-form test coverage proves statement indicators extract from quarterly reports and form-incompatible indicators are skipped.

**Non-Goals:**
- Re-parsing the full quarterly report outline (the outline parser is unchanged; only a targeted body-text fallback for the three statements is added).
- Extracting narrative-section indicators (MD&A, risk management, HR, notes) from quarterly reports — these sections don't exist in Q1/Q3, and `report_type` filtering already skips them.
- Changing the `indicator_rules.json` schema (the `report_type` field already exists on CSV-sourced rules).
- Supporting the 摘要 (summary) forms or English-language reports.

## Decisions

### Decision 1: `form` parameter on `extract_indicators_by_position`, defaulted to `年度报告`

The `form` flows through `extract_indicators(form=...)` → `_build_ctx(form=...)` → `cninfo_client.query_announcements(form=...)`. The four CNINFO periodic form names (`年度报告`/`半年度报告`/`第一季度报告`/`第三季度报告`) are already in `_FORM_CATEGORIES`. Default `年度报告` preserves the existing contract.

**Alternative considered**: a separate `extract_indicators_quarterly` tool — rejected because it would duplicate the batch engine; one parameter is simpler and the form is already a `query_announcements` concept.

### Decision 2: `report_type` filtering partitions rules into `skipped` before delegation

For each CSV indicator resolved to a rule, check `rule.get("report_type", "")`. Map the `form` argument to a compatibility key:
- `年度报告` → `年报`
- `半年度报告` → `半年报`
- `第一季度报告` / `第三季度报告` → `季报`

If the compatibility key is NOT a substring of `rule["report_type"]`, route to `skipped` with `reason: f"not in {form}"`. This runs before the `extract_indicators` call, so form-incompatible rules never trigger a PDF fetch or LLM call.

**Alternative considered**: filtering inside `extract_indicators` — rejected because `extract_indicators` operates on rule objects (not CSV rows) and the `report_type` field is CSV-sourced; keeping the filter in `extract_indicators_by_position` (the CSV entry point) is cleaner. Rules without `report_type` (hand-authored banking rules) default to `年报/半年报/季报` (broadly applicable) so they aren't wrongly skipped.

### Decision 3: Body-text statement fallback in `_resolve_section`

When the outline-based resolution misses for a statement-module rule (`balance_sheet` / `income_statement` / `cashflow`), fall back to searching the raw report text for the canonical statement title:

- `balance_sheet` → search for `合并资产负债表` (then `资产负债表`, then `合并及公司资产负债表` for the ICBC quarterly variant)
- `income_statement` → `合并利润表` (then `利润表`, then `合并及公司利润表`)
- `cashflow` → `合并现金流量表` (then `现金流量表`, then `合并及公司现金流量表`)

Slice from the title line's start to the next statement title or the next `第X节`/`一、` top-level heading that follows. Return the sliced text as the section body with `matched = "<body-text: 合并资产负债表>"`.

**Alternative considered**: enhancing `parse_outline` to capture standalone statement titles — rejected because it would change outline semantics for every caller (cache, `get_section`, `get_financial_statements`) and risk regressions. The targeted fallback only affects `_resolve_section` and is invisible to other paths.

### Decision 4: Hand-authored rules without `report_type` default to broadly applicable

46 hand-authored banking rules have no `report_type` field (they predate the CSV migration). Rather than skip them for quarterly forms, treat a missing `report_type` as `年报/半年报/季报` (broadly applicable) so bank statement indicators (资产总计, 负债合计, etc.) still extract from quarterly reports. The migration's `_annotate_existing` already backfills `report_type` from the CSV for the 44 overlapping rules; the 2 non-overlapping hand-authored rules (`拨贷比_coverage`, `不良率_coverage` — computed shadows) are `source_type: "computed"` and bypass the filter anyway.

### Decision 5: Result bundle records `form` and form-skipped indicators

The bundle gains `form` (the form used) and the `skipped` list gains entries `{indicator, source_type: "form_filter", note: f"not in {form}"}` for form-incompatible indicators. The CSV output (`scripts/extract_indicators_by_position.py`) gains a `form` column in its provenance and `status: "skipped_form"` rows.

## Risks / Trade-offs

- **[Body-text slicing may capture table noise]** → The fallback slices from the statement title to the next statement/heading, which may include continuation pages. Mitigation: the python extractors (`table_row`, `regex_amount`) already scan line-by-line for the indicator name and read the adjacent number, so extra noise lines don't corrupt extraction — they just don't match. The LLM path receives up to `max_chars=12000` of section text and is instructed to return null for absent indicators.
- **[ICBC quarterly uses `合并及公司资产负债表–按中国会计准则编制`]** → The fallback tries `合并资产负债表` first (fails for ICBC), then `资产负债表` (substring of `合并及公司资产负债表` — succeeds). 茅台 quarterly uses `合并资产负债表` directly. Both resolve.
- **[Form filter may wrongly skip a hand-authored rule]** → Mitigated by Decision 4: missing `report_type` defaults to broadly applicable. The 44 annotated rules get the CSV's `report_type`; the 2 computed shadows bypass the filter.
- **[Semi-annual reports resolve fewer indicators for non-banks]** → Expected: 茅台 半年报 doesn't have bank-specific sections (风险管理/资本充足率). `applies_to` already filters these for non-banks; the `report_type` filter is orthogonal (it skips by form, not by company).
- **[CNINFO year-window bug for bank semi-annual titles]** → Pre-existing: `query_announcements(year=2023)` misses `工商银行2023半年度报告` because the title lacks `年` between `2023` and `半年度`. Not in scope for this change (workaround: pass `year=None` and filter by title). Documented in the proposal's test plan.

## Migration Plan

1. CSV already fixed and re-migrated (321 rules, in sync).
2. Implement `form` param + `report_type` filter + body-text fallback in `indicators_client.py`.
3. Add `--form` to `scripts/extract_indicators_by_position.py`.
4. Add `find_statement_in_text` helper to `cnreport_tools.py`.
5. Run the 2-company × 4-form integration test against cached reports (offline).
6. Regenerate `docs/indicators-methodology.md` + `docs/indicators-coverage.{md,csv}`.
7. Update README indicator section.

**Rollback**: revert `indicators_client.py`, `scripts/extract_indicators_by_position.py`, `cnreport_tools.py`. The CSV fix is a strict improvement (duplicates removed) and doesn't need rollback.

## Open Questions

- Should the body-text fallback also handle `Statement of Comprehensive Income` (综合收益表)? Currently the CSV marks those indicators as `年报/半年报/季报`, but quarterly reports fold comprehensive income into the income statement. Decision: leave as-is — the income-statement fallback covers the data; the comprehensive-income indicators will extract from the income statement section.
