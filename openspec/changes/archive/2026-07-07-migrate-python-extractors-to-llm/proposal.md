## Why

The 227 Python-extractor rules (`python:table_row`, `python:percent_value`, `python:headcount`) have a **22% hit rate** against real annual reports, and the "hits" are unreliable — `table_row` picks up ordinals/years/face-values instead of financial figures, `headcount` returns the same total (419,252) for every education/function sub-category, and `percent_value` fails because derived ratio labels don't appear verbatim in report text. The LLM extractor is already proven on 62 indicators and can parse table structure, compute ratios, and handle page-split cells — capabilities the regex-based Python extractors fundamentally lack.

## What Changes

- **BREAKING**: Convert all 227 `python:*` extractor rules in `indicator_rules.json` to `extractor: "llm"`, removing the `python:table_row`, `python:percent_value`, and `python:headcount` extractor dispatch paths from the runtime (the `indicators_extractors.py` registry and its `register()` calls are removed).
- Fix section selectors for the three major financial statements (`资产负债表` / `利润表` / `现金流量表`) so they resolve to the actual consolidated statement table, not the MD&A analysis sub-section.
- Fix section selectors for notes/risk sections (`财务报表附注`, `风险管理 — 流动性风险`, `风险管理 — 信用风险`, `股东情况`, `客户情况`, `供应商情况`) by adding correct aliases to the section map and adjusting selector chains.
- Assign all migrated indicators to the correct Pydantic model per module so the LLM call sends the right JSON schema and field descriptions.
- Add a validation script that re-runs extraction against cached reports and reports the before/after delta in hit count and value accuracy.

## Capabilities

### New Capabilities
- `llm-section-batch-extract`: Batch LLM extraction that groups all report-type indicators sharing the same resolved section into a single LLM call per module, reducing API calls from N (one per indicator) to M (one per section × module).

### Modified Capabilities
- `indicator-rules`: All `source_type: "report"` rules SHALL use `extractor: "llm"` — the `python:*` extractor type is removed. The `extractor` field on report rules SHALL be `"llm"` or omitted (defaults to `"llm"`). The `indicators_extractors.py` registry module is deleted.
- `llm-indicator-extract`: The LLM extractor SHALL receive the full set of indicators for a resolved section (not just one), grouped by Pydantic model, so a single call per section×module extracts all sibling indicators.
- `indicator-position-extract`: Section resolution for three-statement modules (`balance_sheet`, `income_statement`, `cashflow`) SHALL prefer the consolidated statement table over the MD&A analysis sub-section.

## Impact

- **indicator_rules.json**: 227 rules change `extractor` from `python:*` to `"llm"`. Selector chains for ~40 rules targeting `资产负债表`/`利润表`/`现金流量表`/`风险管理`/`股东情况` are corrected.
- **indicators_extractors.py**: Deleted (no more Python extractor registry).
- **indicators_client.py**: `_run_extractor` simplifies — the `python:` dispatch branch is removed. The LLM batch path becomes the only report extraction path.
- **indicators_models.py**: Pydantic models for `report_section` module need to accommodate the 227 migrated indicators (field additions).
- **report_section_map.json**: New alias entries for `资产负债表`, `利润表`, `现金流量表`, `风险管理`, `股东情况`, `客户情况`, `供应商情况`.
- **Cost**: LLM calls increase — previously 0 calls for python-extractor rules, now ~15-20 calls per report (one per resolved section×module). Cached via `llm_section_cache` so repeat runs are free.
