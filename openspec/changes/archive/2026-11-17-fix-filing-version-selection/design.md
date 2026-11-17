## Context

见 proposal.md — Why。设计层要注意的现状约束有三条：

1. 选文件的逻辑已经在仓里存在两份：`scripts/bank_ingest.py::_pick_report`（判型 + 期次 +
   摘要/H股过滤）与 `scripts/agri_ingest.py:90-95`（在其上补「更正通知不算报告本体 +
   更正后优先」）。生产 MCP 工具的三处 `filings[0]` 都没接这两份纪律。
2. `agri_ingest` 的补丁是**猴补丁**形式（`B._pick_report = _pick_report`），因为它复用
   `bank_ingest` 的整条 ingest 机械。生产工具直接 import 它会把整条 ingest 依赖链拖进
   MCP 进程。
3. 三个工具取文件的位置各不相同：`get_section` 与 `get_financial_statements` 按
   `form+year` 查，`get_special_report` 按 `category+year` 查。选取规则必须对两者皆成立。

## Goals / Non-Goals

**Goals**
- 一处实现，四个调用点共用，杜绝第五处再写 `filings[0]`。
- 行为对既有正常样本完全不变（无更正版本时取原序首条）。

**Non-Goals**
- 不把 `bank_ingest` 的判型/期次/摘要过滤搬进来——那是 ingest 流水线的事，MCP 工具的
  查询参数（`form`/`year`/`category`）已经表达同样的约束。
- 不做数字级来源（从 PDF 表格里逐格取坐标）——需要表格解析，是另一个量级的工作。
- 不改 `list_filings` / `get_filing` 的既有返回形状。

## Decisions

**D1：新建 `_pick_report_filing()`，而不是 import `agri_ingest._pick_report`。**
理由：`agri_ingest` 依赖 `bank_ingest` 的 ingest 机械与 `cnreport_database`，MCP 进程
不需要这些。规则本身只有 5 行，复制规则比重建整条依赖链便宜。
替代方案（去掉：把选版规则下沉到 `cninfo_client`）——被否，因为 `cninfo_client` 的职责
是"查询"，它返回的列表就是事实；"哪一个是要解析的报告"是调用方的语义判断。

**D2：全被滤光时退回 `filings[0]`，不返回空。**
理由：坏选择在结果里可见（`missing` 会显示缺表），空选择会被上层误读成"这家公司没有年报"，
是更坏的错误。这一点写在函数的 docstring 里，防止后人"优化"成返回 None。

**D3：四个工具都改，不只改 `get_financial_statements`。**
理由：`get_section` 和 `get_special_report` 同样会落在更正通知上——只是它们返回的是
"某节没找到"而不是"三张表全缺"，更容易被当成正常缺节而忽略。同一个 bug 换个面貌而已。

**D4：`get_financials` 不假装能追溯，显式声明 `announcement_traceable: false`。**
理由：它的数据来自 Sina 聚合端点（一次返回所有报告期），结构上就不对应任何一份披露文件。
两个选项——补一个假来源，或声明不可追溯。前者会在用户拿它做审计时炸掉，后者至少诚实。
与 `a83115c`（akshare 拿错年份不许标成请求年份）是同一条纪律：来源标签不许说谎。

## Risks / Trade-offs

- **风险**：标题里出现「更正」但实际是报告本体的情况（例如「更正后说明」这类命名）。
  缓解：判据是"含更正 且 不含更正后"，`（更正后）`/`更正后` 都会被 `更正后` 命中，
  只剩「更正说明」这种 title 会被误滤——而它确实也不是报告本体。真实样本（600965）
  三个版本命名符合预期。
- **风险**：全被滤光时退回原序首条，等于"知道可能有错但照做"。权衡见 D2：可见的错
  优于不可见的空。`missing` 字段是这条兜底的告警面。
- 既有 7 条测试失败与本改动无关（改前改后同为 7 failed），已用 `git stash` 双向核对。
