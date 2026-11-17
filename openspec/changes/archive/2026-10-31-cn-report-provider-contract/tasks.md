## 1. run() 显式未实现（catalog.py）

- [x] 1.1 删掉 `from cnreport_tools import dispatch as server_dispatch`；
  `run()` 改为：声明命令与未知命令一律抛 `NotImplementedError`，消息含
  命令名 + 真实替代入口（MCP 工具面：`python3 server.py`，工具如
  `list_outline`/`extract_section`/`extract_indicators`/`list_filings`）
- [x] 1.2 模块 docstring 与 run() docstring 如实声明：functions 为声明性
  清单，执行入口是 MCP 工具面（不暗示 run() 可执行）

## 2. Provider 冒烟测试（新增 test_provider.py）

- [x] 2.1 9 个声明命令逐一断言抛 `NotImplementedError`（不是 ImportError）
- [x] 2.2 未知命令同断言；消息含替代入口提示
- [x] 2.3 `cnreport_tools` 无 `dispatch` 属性断言（防悬空 import 复活）
- [x] 2.4 `python3 -m pytest test_provider.py -q` 全绿

## 3. 提交

- [x] 3.1 提交推送（gitee + origin）；commit message 标注 handoff ④ 实例二
