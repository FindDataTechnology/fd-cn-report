# report-filing-provenance Specification

## Purpose

定义「从巨潮披露列表里挑哪一个文件来解析，以及解析结果怎么标来源」的契约。巨潮按发布日倒序返回同一期报告的原版、更正通知、更正后版本——把它们当成可互换的候选会让提取工具静默拿到不含财务报表的通知。同时约定：能给出公告级来源的路径必须给出（`announcement_id` / 标题 / 发布日），给不出的必须显式声明不可追溯，不许沉默。

## Requirements

### Requirement: Filing selection drops correction notices

从巨潮披露列表里为解析挑选文件时，实现 SHALL 滤除更正**通知**类公告——判据是标题
含「更正」且不含「更正后」。更正通知是告知存在新版本的公告，其正文不含财务报表；
把它当报告本体解析会得到空结果而非报错。

#### Scenario: 同日发布更正通知与更正后报告

- **WHEN** 披露列表同时含「关于更正《2024年年度报告》的公告」与「2024年年度报告（更正后）」
- **THEN** 选中的是后者，且解析出的三张报表不为空

#### Scenario: 只有更正通知

- **WHEN** 列表里所有候选都是更正通知
- **THEN** 实现退回原序首条，不返回空选择
- **THEN** 结果里的缺表信息保持可见，不被静默成"没有这份报告"

### Requirement: Corrected version outranks the original

同一期同时存在原版与「（更正后）」版本时，实现 SHALL 选更正后版本，无论查询返回顺序
如何。查询顺序按发布日倒序，因此同日发布的更正后版本可能排在原版之后。

#### Scenario: 原版与更正后同日发布

- **WHEN** 列表含「2024年年度报告」与「2024年年度报告（更正后）」
- **THEN** 选中的是「（更正后）」那条

#### Scenario: 没有更正版本时保持查询顺序

- **WHEN** 列表里没有任何「（更正后）」标题
- **THEN** 选中项与查询返回的第一条一致（不改变既有行为）

### Requirement: Extracted results carry announcement provenance

从具体披露文件提取内容的工具 SHALL 在返回里带公告级来源：`announcement_id`、
`announcement_title`、`published`。页级定位（`outline_entry.page`）已在，两者合起来
让调用方不必解析 `pdf_url` 就能完成"数字 → 原文"的追溯。

#### Scenario: 取三大报表

- **WHEN** 调用 `get_financial_statements(ticker, year)` 且文件解析成功
- **THEN** 返回含 `announcement_id`（非空）与 `announcement_title`
- **THEN** 同一 `announcement_id` 也被传给报告缓存，使缓存键与来源一致

#### Scenario: 取单节正文

- **WHEN** 调用 `get_section` 或 `get_special_report(section=…)`
- **THEN** 返回含 `announcement_id` 与 `announcement_title`

### Requirement: Untraceable sources declare themselves

无法给出公告来源的取数路径 SHALL 在返回里显式声明不可追溯（`announcement_traceable:
false`）并说明来源类型。MUST NOT 静默省略——缺字段会被读成"能追溯"。

#### Scenario: akshare 聚合表取数

- **WHEN** 调用 `get_financials`（走 Sina 聚合表，一次返回所有报告期）
- **THEN** 返回含 `announcement_traceable: false` 与 `source`
- **THEN** 需要逐数字追溯的调用方被指向 `get_financial_statements`
