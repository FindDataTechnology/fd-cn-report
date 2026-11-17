## Context

当前指标抽取由规则驱动：规则集存放于 `indicator_rules.json`，其中 `source_type:"report"` 且 `extractor:"llm"` 的指标通过 `source.selectors[]` 定位到报告章节，再将章节文本送入 LLM 做结构化抽取。实际运行结果会落盘到 `out/`，包含每次抽取的 `missing/unresolved/skipped` 列表及每个指标的 `provenance/source` 信息。

问题集中在两类场景：

- 规则不可达：指标在规则集中缺失、或不符合公司适用性过滤，导致无法进入抽取流程。
- 章节定位不稳：不同公司/不同报告类型（年报/半年报/季报）存在章节标题差异、层级差异，导致 selector 命中率低或命中到非目标上下文，从而影响 LLM 抽取稳定性。

设计目标是把“发现缺口—定位原因—修正规则—回归验证”固化为可重复流程，并降低规则维护成本。

## Goals / Non-Goals

**Goals:**

- 对年报/半年报/季报三类定期报告，提升 report+LLM 指标规则的章节命中率与抽取成功率。
- 提供规则缺口审计产物：明确哪些指标缺失/不可达/常失败，以及建议的章节候选与修复优先级。
- 引入“章节标题别名映射”，减少 selector 里对具体标题写死的依赖，提升跨公司版式鲁棒性。
- 将验证闭环产品化：基于 out/ 的基线样例做回归检查，规则改动可量化评估。

**Non-Goals:**

- 不重写三大表（akshare）与 computed 指标的抽取逻辑。
- 不引入新的 OCR/版面分析依赖，不做全量“从整份 PDF 抽取所有指标”的大模型重构。
- 不在本次变更中建设可视化规则管理 UI（若需要，后续 change 单独推进）。

## Decisions

- 章节别名映射以独立数据文件维护（例如 `docs/report_section_map.json` 或同等位置），并作为 selector 解析时的可选扩展层：selector 的 `section` 可写“规范化键”或具体标题，解析时统一扩展为候选标题集合再匹配 TOC/outline。
- 规则缺口审计优先复用现有事实来源：
  - 规则侧：`indicator_rules.json`（关注 `source_type:"report"`、`extractor:"llm"`、`report_type` 过滤、`selectors[]`）
  - 结果侧：`out/*.json`（关注 `missing/unresolved` 与 `indicators[*].value == null` 的失败信号）
  审计产物聚合后输出为机器可读 JSON（必要时辅以 CSV），作为修复输入与 CI 回归依据。
- 章节定位策略以“多级 fallback”取代“单标题命中”：
  - 先尝试公司/行业特定 selector
  - 再尝试报告类型（年/半/季）对应的别名集合
  - 最后尝试宽泛候选章节（如“财务报表附注”“管理层讨论与分析”等）作为降级上下文

## Risks / Trade-offs

- [章节别名过宽导致误命中] → 为别名映射分层（强别名/弱别名），并在 provenance 中记录实际命中的标题，便于回溯与收敛。
- [规则改动导致历史结果不可复现] → 保留原 selector 串联语义，别名扩展作为“额外可选路径”；回归基线以 out/ 样例验证关键指标。
- [审计依赖 out/ 样例覆盖不足] → 当 out/ 缺少某类报告时，补充下载少量公开报告作为夹具，并将其纳入最小回归集。

