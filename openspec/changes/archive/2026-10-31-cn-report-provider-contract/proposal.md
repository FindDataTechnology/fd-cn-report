# cn-report-provider-contract — provider `run()` 悬空修复（显式未实现标注）

## Why

`gov-documents-vertical` 验收报告 §8.1 记录项（`docs/handoff/fd-cn-gov-dangling-dispatch.md` ④，
实例二）：`FDcnReportProvider.run()` 里 `from cnreport_tools import dispatch as server_dispatch`，
而 `cnreport_tools.py` **没有 `dispatch`**（全是具体工具函数）——该路径一调即
`ImportError`（实测复现：`cannot import name 'dispatch' from 'cnreport_tools'`）。
`fd-open-data-protocol` 的 `DataProvider.run()` 契约在本源名存实亡，且**让
「未实现」伪装成「实现有 bug」**——这正是要修的信息诚实问题。

核验同时确认：CATALOG 声明的 9 个命令与仓内真实可调用面**没有 1:1 对应**——
真实面是 44 个 MCP 工具（`server.py` 的 `@app.tool`）；平台侧消费另有既有
规范（`cn-report-registry` spec：经 `fd-open-data-mcp` 的 curated seed，明确
「SHALL NOT rely on MCP-tool introspection」）。故本 change 采用 handoff 的
推荐路径（显式未实现标注），不发明第三套命令语义。

## What Changes

- **`run()` 显式拒绝**（照 `fd-industry-data` 的 `Unknown command` 处理形态——
  显式抛出而非静默错误）：
  - 声明清单内的命令 → `NotImplementedError`，消息说明该命令尚无执行入口、
    指向真实可用面（MCP 服务器工具：`list_outline`/`extract_section`/
    `extract_indicators`/`list_filings` 等，`python3 server.py` 起服）；
  - 清单外命令 → `NotImplementedError`「未知命令」同形；
  - 删除悬空 import；`run()` 的任何入参路径**绝不** `ImportError`。
- **Provider 冒烟测试**（本仓首次 provider 级测试，`test_provider.py`）：
  全部 9 个声明命令与未知命令均抛 `NotImplementedError`（不是 `ImportError`）、
  消息含替代入口；`cnreport_tools` 无 `dispatch` 属性断言（防悬空 import 复活）。
- **文档口径**：`catalog.py` 模块 docstring 与 `run()` docstring 如实声明
  「functions 为声明性清单，执行入口是 MCP 工具面」——把未实现变成显式契约。

明确不做：

- **不发明 run() → MCP 工具的映射桥**：9 个声明命令与 44 个真实工具无 1:1
  对应（如 `cninfo_annual_report_outline(company, year, stock_code)` 与
  `list_outline(source)` 参数形状不同），凭空映射会造出第二套语义——
  正是 handoff 判词所禁。
- **不重写 9 个声明命令清单**：平台消费面由既有 spec（curated seed）钉死，
  仓库目录清单是声明性的；其是否随真实工具面重整，属报告线的产品决定
  （已记录为遗留，见 handoff 文档更新）。
- **不动 fd-cn-gov**：同型缺陷的另一半已在彼仓 `datasource-provider-contract`
  change 修复（彼处有真实可派发目标，走了真实现路径）。

## Capabilities

### New Capabilities

- `datasource-provider`: fd-cn-report 作为 `fd-open-data-protocol` DataProvider
  的诚实契约——`run()` 对声明命令与未知命令均显式 `NotImplementedError`
  并指明真实入口；不存在指向未定义属性的 import。

## Impact

- **代码**：`catalog.py`（run() + docstring）、新增 `test_provider.py`；
  不动 `server.py`、不动 44 个 MCP 工具、不动数据面。
- **兼容**：`load_catalog("catalog:CATALOG")` 路径不变；`registry()` 不变。
  悬空路径当前无调用方命中（handoff 核验），故无行为回归面。
- **风险**：极低——纯契约诚实化，无迁移、无部署、无外部系统。
