## 1. CSV data-quality fix (DONE during research)

- [x] 1.1 Remove 32 exact-duplicate rows from `docs/indicators_position.csv` (353→321 rows).
- [x] 1.2 Normalize `report_type` values: `季报/半年报/年报`→`年报/半年报/季报` (2 rows), `年度`→`年报` (1 row).
- [x] 1.3 Re-run `scripts/migrate_indicators_csv.py` to sync `indicator_rules.json` (321 rules, in sync).

## 2. Body-text statement fallback (`cnreport_tools.py`)

- [x] 2.1 Add `find_statement_in_text(text, module)` — searches raw report text for the canonical statement title (`合并资产负债表` → `资产负债表` → `合并及公司资产负债表` for balance_sheet; analogously for income_statement / cashflow). Returns `(start_offset, end_offset)` slicing from the title line to the next statement title or top-level numbered heading (`第X节` / `一、` at line start).
- [x] 2.2 Add `extract_statement_text(text, module)` wrapping `find_statement_in_text` to return the sliced body string (or `None` when the title isn't found).
- [ ] 2.3 Unit-test the helper against ICBC Q1 (title `合并及公司资产负债表–按中国会计准则编制`) and 茅台 Q1 (title `合并资产负债表`) cached texts.

## 3. Engine: `form` parameter + `report_type` filter (`indicators_client.py`)

- [x] 3.1 Add `_FORM_COMPAT_KEY` mapping: `年度报告`→`年报`, `半年度报告`→`半年报`, `第一季度报告`→`季报`, `第三季度报告`→`季报`.
- [x] 3.2 Add `_form_compatible(rule, form)` — returns True if the compat key is a substring of `rule.get("report_type")` or the rule has no `report_type` (defaults to broadly applicable).
- [x] 3.3 Extend `extract_indicators_by_position` signature with `form: str = "年度报告"`. Partition CSV-named rules: `external` → `skipped` (existing); form-incompatible → `skipped` with `{source_type: "form_filter", note: f"not in {form}"}`; the rest → `delegate_names` passed to `extract_indicators(form=form, ...)`.
- [x] 3.4 Pass `form` through `extract_indicators` → `_build_ctx` (already accepts `form`); verify the correct PDF is fetched for each form via `query_announcements(form=form)`.
- [x] 3.5 Add `form` to the result bundle header (next to `year`, `pdf_url`).
- [x] 3.6 In `_resolve_section`, after the outline walk + `resolve_statement` fallback miss, call `cnreport_tools.extract_statement_text(text, rule["module"])` for statement modules; return the sliced body with `matched = f"<body-text: {title}>"` when found.

## 4. CLI: `--form` flag (`scripts/extract_indicators_by_position.py`)

- [x] 4.1 Add `--form {年度报告,半年度报告,第一季度报告,第三季度报告}` argument (default `年度报告`).
- [x] 4.2 Pass `form` to `indicators_client.extract_indicators_by_position`.
- [x] 4.3 Include `form` in output filenames when non-default: `<stock>_<year>_<form>.json` (and `.csv`).
- [x] 4.4 Record `form` in JSON provenance and add form-filtered rows to the CSV `skipped` section.

## 5. Tests (`test_cnreport.py`)

- [x] 5.1 Test `_form_compatible`: `分红金额` (年报) skipped for `第一季度报告`; `资产总计` (年报/半年报/季报) attempted for all forms; hand-authored rule without `report_type` attempted for all forms.
- [x] 5.2 Test body-text fallback: `find_statement_in_text` finds the Balance sheet in ICBC Q1 text and the income statement in 茅台 Q1 text; returns `None` when the title is absent.
- [x] 5.3 Test `extract_indicators_by_position(form="第一季度报告")` against cached 茅台 Q1: statement indicators (`资产总计`, `营业收入`, `净利润`) resolve; `分红金额` appears in `skipped` with `source_type: "form_filter"`; `PE-TTM` appears in `skipped` with `source_type: "external"`.
- [x] 5.4 Test default `form` is `年度报告`: `extract_indicators_by_position("工商银行", 2023)` behaves identically to before (regression).
- [x] 5.5 Add a 2-company × 4-form integration test using cached reports (601398 + 600519 × 年度/半年度/Q1/Q3), asserting: (a) annual resolution ≥ 80% for the bank, (b) quarterly resolution > 0% (was 0% before the fallback), (c) form-incompatible indicators are in `skipped`.

## 6. Docs + validation

- [x] 6.1 Regenerate `docs/indicators-methodology.md` (`python indicators_client.py --render-methodology`).
- [x] 6.2 Refresh `docs/indicators-coverage.{md,csv}` (`--render-coverage`, `--write-coverage-csv`).
- [x] 6.3 Update `README.md` indicator section: document the `form` parameter and the `--form` flag.
- [x] 6.4 Run `openspec validate multi-form-indicator-extract` and fix any drift.
- [x] 6.5 Run `.venv/bin/python -m pytest test_cnreport.py -v -p no:logfire` (offline).
- [x] 6.6 Run the 2-company × 4-form extraction end-to-end via the CLI, writing results to `./out/`, and spot-check that 茅台 Q1 `资产总计` and ICBC Q1 `净利润` have non-empty values.
