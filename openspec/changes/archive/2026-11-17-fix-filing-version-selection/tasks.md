# Tasks — fix-filing-version-selection

> 已于 `c53924a` 实施完毕。本文件记录当时实际做了什么，勾选项是已完成的，
> 不是待办计划。

## 1. 选版纪律

- [x] 1.1 新增 `_pick_report_filing()`：滤更正通知 → 更正后优先 → 全滤光退回原序首条
- [x] 1.2 `get_section` 的 `top = filings[0]` 改用该函数
- [x] 1.3 `get_special_report` 同上
- [x] 1.4 `get_financial_statements` 同上
- [x] 1.5 docstring 写明"全滤光退回"是有意的，防止后人改成返回 None

## 2. 公告级来源

- [x] 2.1 `get_financial_statements` 返回 `announcement_id` / `announcement_title` / `published`
- [x] 2.2 `get_section` 返回同上
- [x] 2.3 `get_special_report`（含 section 分支与 no-section 分支）返回同上
- [x] 2.4 `get_financials` 返回 `announcement_traceable: false` + `source: sina_akshare_aggregate`
- [x] 2.5 `get_financials` docstring 说明"要追溯请用 get_financial_statements"

## 3. 验证

- [x] 3.1 真实 600965/2024：修复前 `pdf=1223057356`（更正通知）`missing=三表全缺`；
      修复后 `pdf=1223057355`（更正后）`missing=[]`
- [x] 3.2 回归 600519/2023：取到的 PDF 不变（`1219506510`）
- [x] 3.3 真实 `get_section` 带出 `announcement_id`
- [x] 3.4 新增 6 条测试：pick 四态（真实顺序 / 无更正 / 全更正退回 / title 缺失）
      + 两处 provenance
- [x] 3.5 测试基线双向核对：`git stash` 前后同为 7 failed / 72 passed —— 那 7 红是既有的

## 4. 归档

- [x] 4.1 `openspec validate fix-filing-version-selection --strict` → valid
- [x] 4.2 `openspec archive` —— delta 合进 `openspec/specs/report-filing-provenance/`
