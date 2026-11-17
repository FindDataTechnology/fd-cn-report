## 1. Migrate Rules in indicator_rules.json

- [x] 1.1 Write a migration script that flips all `python:*` extractors to `"llm"` in indicator_rules.json (idempotent — re-running produces no diff)
- [x] 1.2 Run the migration and verify all 227 `python:*` rules now have `extractor: "llm"`
- [x] 1.3 Verify the 62 existing `llm` rules are untouched

## 2. Fix Section Selectors

- [x] 2.1 Add aliases to report_section_map.json for `资产负债表` → `["合并资产负债表", "合并及公司资产负债表", "银行资产负债表"]`, `利润表` → `["合并利润表", "合并及公司利润表", "银行利润表"]`, `现金流量表` → `["合并现金流量表", "合并及公司现金流量表", "银行现金流量表"]`
- [x] 2.2 Add aliases for `风险管理` → `["七、金融风险管理", "风险管理"]`, `股东情况` → `["股本变动及主要股东持股情况", "主要股东"]`, `人力资源管理` → `["人力资源管理与员工机构情况"]`
- [x] 2.3 Pass `form=ctx.form` to `_resolve_section` in the batch extraction path of `extract_indicators`

## 3. Remove Python Extractor Code

- [x] 3.1 Delete `indicators_extractors.py`
- [x] 3.2 Remove the `python:` dispatch branch from `_run_extractor` in `indicators_client.py`
- [x] 3.3 Remove the `python_rules` branch from `_extract_one_section` in `extract_indicators` — all report rules in a section go to `_llm_extract_section`
- [x] 3.4 Simplify `_effective_extractor` — `python` mode always returns `"llm"` for report rules (which means `skipped` in python mode)

## 4. Validate & Test

- [x] 4.1 Run `pytest test_cnreport.py` — all existing tests must pass (update assertions that reference python extractors)
- [x] 4.2 Run `scripts/test_python_extractors.py` (adapted) against the cached ICBC report — verify 0 python-extractor rules remain
- [x] 4.3 Run the gap audit tool against `out/601398_2023.json` — verify the `missing_section` count drops for three-statement modules
- [x] 4.4 Add a regression test that verifies the batch path groups all report rules by section and makes one LLM call per section×module (mock `call_llm_pydantic`)
