# datasource-provider Specification

## Purpose
TBD - created by archiving change cn-report-provider-contract. Update Purpose after archive.

## Requirements

### Requirement: Provider run() 显式未实现而非悬空 import

`FDcnReportProvider.run(command, params)` SHALL 对 CATALOG 声明的全部命令
（9 个）与任何未知命令抛出 `NotImplementedError`，消息 SHALL 说明该命令
尚无执行入口并指明真实可用面（MCP 服务器工具面）；SHALL NOT 存在任何
指向不存在模块属性的 import。`cnreport_tools` SHALL NOT 被要求提供
`dispatch`（该属性从未存在；修前实测：`from cnreport_tools import dispatch`
一调即 `ImportError`，把未实现伪装成实现缺陷）。

#### Scenario: 声明命令抛显式未实现

- **WHEN** `run("cninfo_annual_report_outline", {})` 被调用
- **THEN** 抛出 `NotImplementedError`
- **AND** 消息指明替代入口（MCP 工具面 / 启动方式）
- **AND** 抛出的是 `NotImplementedError` 而非 `ImportError`

#### Scenario: 未知命令同形拒绝

- **WHEN** `run("does_not_exist", {})` 被调用
- **THEN** 抛出 `NotImplementedError`（含未知命令名），不是 `ImportError`

#### Scenario: 悬空 import 不得复活

- **WHEN** 静态检查 `catalog.py`
- **THEN** 不存在 `from cnreport_tools import dispatch` 或任何指向
  `cnreport_tools` 未定义属性的 import

### Requirement: 声明清单的诚实口径

`catalog.py` 的模块 docstring 与 `run()` docstring SHALL 如实声明 functions
为**声明性清单**（记录可提供的财报能力与输出列 schema），执行入口为 MCP
工具面；SHALL NOT 暗示 `run()` 已可执行这些命令。

#### Scenario: 文档口径与实现一致

- **WHEN** 阅读 `catalog.py` 的模块与 run() docstring
- **THEN** 明确说明 run() 为显式未实现、替代入口是 MCP 工具面
