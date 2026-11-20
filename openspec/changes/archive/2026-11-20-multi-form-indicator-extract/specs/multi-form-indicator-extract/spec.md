## ADDED Requirements

### Requirement: Multi-form indicator extraction with report_type filtering
The `extract_indicators_by_position` tool SHALL accept an optional `form` argument selecting the CNINFO periodic report form: `年度报告` (default), `半年度报告`, `第一季度报告`, or `第三季度报告`. The chosen form SHALL flow through `extract_indicators` → `_build_ctx` → `cninfo_client.query_announcements(form=…)` so the correct report PDF is fetched and cached. Indicators whose rule `report_type` field does not contain the form's compatibility key (`年报` for 年度报告, `半年报` for 半年度报告, `季报` for 第一季度报告/第三季度报告) SHALL be routed to `skipped` with `source_type: "form_filter"` and `note: f"not in {form}"` before any PDF fetch or LLM call. Rules without a `report_type` field (hand-authored banking rules) SHALL default to `年报/半年报/季报` (broadly applicable) and not be skipped. The result bundle SHALL record the `form` used.

#### Scenario: Extract indicators from a quarterly report
- **WHEN** `extract_indicators_by_position(ticker_or_name="600519", year=2023, form="第一季度报告")` is called
- **THEN** the system fetches the Q1 report PDF, skips indicators whose `report_type` doesn't include `季报` (e.g. `分红金额`, `净利差`), extracts statement line items via the body-text fallback, and returns the bundle with `form: "第一季度报告"` and form-incompatible indicators in `skipped`.

#### Scenario: Default form is annual
- **WHEN** `extract_indicators_by_position(ticker_or_name="工商银行", year=2023)` is called without `form`
- **THEN** the system uses `form="年度报告"` (the existing behavior) and the result bundle records `form: "年度报告"`.

#### Scenario: Annual-only indicators skipped for semi-annual
- **WHEN** `extract_indicators_by_position(ticker_or_name="600519", year=2023, form="半年度报告")` is called
- **THEN** indicators marked `年报` only (e.g. `分红金额`, `前五大客户收入占比`, `A股融资金额`) appear in `skipped` with `note` containing `not in 半年度报告`, and are not attempted against the PDF.

#### Scenario: External indicators still skipped
- **WHEN** `extract_indicators_by_position(ticker_or_name="工商银行", year=2023, form="第一季度报告")` is called
- **THEN** `source_type: "external"` indicators (PE-TTM, PB, 市值) remain in `skipped` with `source_type: "external"` (unchanged), in addition to the form-filtered skips.

### Requirement: Body-text statement fallback for quarterly reports
When the outline-based section resolution misses for a statement-module rule (`balance_sheet`, `income_statement`, `cashflow`), the engine SHALL fall back to searching the raw report text for the canonical statement title. For each statement module, the fallback SHALL try the consolidated title first (`合并资产负债表` / `合并利润表` / `合并现金流量表`), then the un-prefixed title (`资产负债表` / `利润表` / `现金流量表`), then the bank quarterly variant (`合并及公司资产负债表` / `合并及公司利润表` / `合并及公司现金流量表`). The fallback SHALL slice from the title line to the next statement title or the next top-level numbered heading (`第X节` / `一、`) that follows, and return the sliced text as the section body. This fallback SHALL only activate when the outline resolution returns nothing, so annual and semi-annual reports (whose outlines contain statement titles) are unaffected.

#### Scenario: ICBC Q1 balance sheet resolves via body-text fallback
- **WHEN** the engine resolves a `balance_sheet` rule against the 工商银行 2023 Q1 report (whose outline lacks `合并资产负债表`)
- **THEN** the body-text fallback finds `合并及公司资产负债表` (via the `资产负债表` substring), slices the balance-sheet section, and returns it as the section body so `资产总计` / `负债合计` / `现金及存放中央银行款项` extract correctly.

#### Scenario: 茅台 Q1 income statement resolves via body-text fallback
- **WHEN** the engine resolves an `income_statement` rule against the 贵州茅台 2023 Q1 report (whose outline only has `四、季度财务报表`)
- **THEN** the fallback finds `合并利润表` in the body text, slices the income-statement section, and returns it so `营业收入` / `净利润` / `基本每股收益` extract correctly.

#### Scenario: Annual report unaffected by fallback
- **WHEN** the engine resolves a `balance_sheet` rule against the 工商银行 2023 年度报告 (whose outline contains `合并资产负债表`)
- **THEN** the outline-based resolution succeeds and the body-text fallback is not activated.
