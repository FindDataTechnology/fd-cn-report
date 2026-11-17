## Why

巨潮按发布日倒序返回同一期报告的原版、更正公告、更正后版本。`get_section` /
`get_special_report` / `get_financial_statements` 三处都直接取 `filings[0]`，于是
当同一天先发「关于更正《X年年度报告》的公告」、再发「X年年度报告（更正后）」时，
取到的是**更正通知**——它不含财务报表，解析结果是三张表全缺。

同时，这些工具的返回值里没有公告级来源字段。用户需求原文要求「每个数字能点回原始
公告」，而调用方拿到 `pdf_url` 之后还得自己 parse 出 `announcement_id` 才能追溯。

## What Changes

- 新增文件选版纪律 `_pick_report_filing()`：滤掉更正通知、更正后版本优先、
  全被滤光时退回原序首条（不返回空，坏选择要可见）。三处取 `filings[0]` 的
  调用点改用它。
- 提取类工具（`get_financial_statements` / `get_section` / `get_special_report`）
  的返回补 `announcement_id` / `announcement_title` / `published`，让每个数字不必
  解析 URL 就能点回公告。
- `get_financials` 走 akshare/Sina 聚合表，结构上拿不到公告来源，显式声明
  `announcement_traceable: false` + `source`，不沉默——沉默会被读成"能追溯"。

## Capabilities

### New Capabilities
- `report-filing-provenance`: 报告文件选版纪律（更正通知 vs 更正后版本）与公告级
  来源字段的契约，覆盖所有从巨潮披露列表里挑文件再解析的提取工具。

### Modified Capabilities
<!-- 无既有 capability 覆盖「从披露列表里选哪个文件」这件事——现有 specs 都在
     文件选定之后才开始描述行为（outline / selector / rule / extractor）。 -->

## Impact

- 代码：`cnreport_tools.py`（一处新函数 + 四个工具返回值）；`test_cnreport.py`（6 条测试）。
- 接口：三个工具的返回**新增**字段（向后兼容）；`get_financials` 新增两个声明字段。
- 行为：`600965`/2024 这类同时存在更正通知与更正后报告的公司，取到的 PDF 会变——这是修复本身。
- 无新依赖、无数据模型变更、不涉及迁移。

**已实施并提交**：`c53924a`。本 change 是补留痕，不是在途提案。
