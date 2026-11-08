# 金额类银行指标：结构化源落档（2026-11-08）

配套 change：`bank-indicator-money-unit-support`。本文是**盘点面**——12 项历史休眠指标的
「能取 / 不能取、为什么、从哪取」，下一个人不用再摸一遍。

## 1. 结论一句话

金额类指标**不在报告正文解析单位**（四次证伪），由结构化源取值，值统一为**元**。
主源已升级为 **akshare（东财报表接口）**：42 家 × FY2019–**FY2025** × 4 项 = **1176 行，零缺失**，
`source_used='akshare'`。**无时滞**（工行接口已到 2026-09-30 季报）。
GTA 面板降为**离线交叉校验**，不再写库——它既滞后一财年（FY2025 全空），且被查出有错值（见 §3.2）。

## 2. 12 项盘点

| 指标 | 状态 | 来源 / 原因 |
|---|---|---|
| 客户存款 | ✅ 有源 | `a0b2103201 其中：吸收存款`，42/42(FY2024) |
| 净利息收入（面板标签「利息净收入」） | ✅ 有源 | `bbd1102000`，42/42 |
| 手续费及佣金净收入 | ✅ 有源 | `b0d1104000`，42/42 |
| 发放贷款及垫款 | ✅ 有源（**净额**口径） | `a0b1201000`，42/42 |
| 贷款和垫款总额 | ❌ 无源 | 面板只有净额变量，无「总额」；由净额加回减值准备属派生，不采用 |
| 风险加权资产合计 | ❌ 无源 | 面板无风险加权资产类变量 |
| 拨贷比_coverage | ❌ 无源 | 无贷款减值准备变量，无法复算 准备/贷款 |
| 不良率 | ❌ 无源 | 无五级分类变量 |
| 逾期贷款率 | ❌ 无源 | 无逾期类变量 |
| 重组贷款率 | ❌ 无源 | 无重组类变量 |
| 逾期90天重组贷款率 | ❌ 无源 | 无逾期/重组类变量 |
| 质押贷款净增加额 | ❌ 覆盖不足 | `c0i2008000` FY2024 全样本仅 7 家非空 |

真源：`fd-cn-report/docs/bank-money-indicator-sources.json`（含逐条原文证据、akshare 列映射、`source_priority`）。

### 2.1 命名规则（会绊人的一处）

`indicator_zh` **必须与 `daas.db` 的 `llm_rules.indicator` 同名**——那是引擎、盘点与 spec 的联结键。
实测撞点：面板标签叫「**利息**净收入」，规则库叫「**净**利息收入」，按名 join 会把这一项静默丢掉；
现以规则库名字为规范名，面板叫法降为 `aliases`，摄入时自动归一（`accepted_names()`）。

`流动性比例（人民币）`不在这张表里，因为它走比率抽取路径且已 5/5 精确（不在金额项之列）。

## 3. 口径陷阱（最重要的一节）

**面板是资产负债表账面口径，含应计利息。** 报告前部的「客户存款总额」「各项贷款」是**本金**
口径。混用差约 1%，且这正是 `harden-bank-indicator-rules` 期错值的形态之一。

### 3.1 两处独立加总实证（证据取自年报原文，**不是**从源反抄）

- 招行 FY2024 存款：本金 `9,096,587` + 应计利息 `98,742` = **`9,195,329`** 百万元 = 面板值
  （FY2023 同法：`8,155,438` + `85,060` = `8,240,498` = 面板值）
- 工行 FY2024 贷款：总额 `28,372,229` + 应计利息 `56,624` − 减值准备 `815,072` = 净额 **`27,613,781`** 百万元 = 面板值

由此定死两条：
1. `客户存款` = 含应计利息口径；观测行带 `caliber` 说明。
2. `发放贷款及垫款` = **净额**，名称与口径都不得写「总额」。

### 3.2 源间交叉校验：10 个不符，全是 GTA 错

akshare 与 GTA 在 FY2019–2024 重叠期共 **724 点**可比，其中 **10 点不符，全部集中在「发放贷款及垫款」**
（客户存款 / 净利息收入 / 手续费三项 **0 不符**）。逐点定谳：

- 江苏银行 `600919` FY2023：akshare `18,359.72` 亿元 vs GTA `17,474.77` 亿元。
  年报正文「2024 年末发放贷款和垫款账面价值 20,387 亿元，较上年末增长 11.04%」反推 2023 = **18,360 亿元**
  → **akshare 对，GTA 错**（差 5.06%）。
- 其余 9 点偏差中位数 0.0092%，含浮点/千元取整差（如 `199,952,296,000` vs `199,952,295,636.67`）。

**结论**：主源只能是 akshare；GTA 仅作交叉校验，且交叉校验的价值已被证实（它查出了 GTA 的错值）。

## 4. 年份边界

| 年度 | 客户存款 | 利息净收入 | 手续费净收入 | 发放贷款及垫款 |
|---|---|---|---|---|
| 2019 | 36 | 36 | 36 | 36 |
| 2020 | 38 | 38 | 38 | 38 |
| 2021 | 42 | 42 | 42 | 42 |
| 2022 | 42 | 42 | 42 | 41 |
| 2023 | 41 | 42 | 42 | 42 |
| 2024 | 42 | 42 | 42 | 42 |
| 2025 | **0** | **0** | **0** | **0** |

（GTA 面板，42 家样本内非空家数——**这是被替换掉的旧源**，FY2025 整列为空。）

akshare 主源的同期分布：**每年 168 行 = 42 家 × 4 项，FY2019–FY2025 全部满格，零缺失**。
缺值时仍按 `statement-missing` / `value-missing` 留痕，不插值、不用相邻年份顶替。

## 5. 已落库数据

- 概念：`financials.customer_deposits` / `financials.net_interest_income` /
  `financials.fee_and_commission_income` / `financials.loans_and_advances_net`（均 `verified=True`，
  `unit=currency`，`frequency=yearly`）→ `financials` 概念总数 55 → **59**
- 观测：**1176 行**，`source_used='akshare'`，date 形如 `YYYY-12-31`，`granularity='year'`，
  每概念 294 行（42 家 × 7 年）
- **单源**：已删除本线此前写的 966 行 `gta-panel` 观测，同一 (概念,主体,日期) 不再双源并存
- 读数面实弹：pod 内 `read` 返回工行 FY2024 `34836973000000` 与 **FY2025 `37311778000000`**，
  `source_used='akshare'`，实体解析到 `entity_id=59`

## 6. 复核命令

```bash
# 主源：akshare 取数 + 核锚（锚的证据取自年报原文，不一致非零退出）
cd fd-cn-report
NO_PROXY=127.0.0.1,localhost ../scraw-fd-open-data-mcp/.venv/bin/python \
  scripts/register_bank_money_from_akshare.py \
  --years 2019-2025 --dump output/akshare-banks-2026-11-08.json --verify

# 交叉校验（对 GTA 的历史 dump，重叠期必须逐值相等）
../scraw-fd-open-data-mcp/.venv/bin/python scripts/register_bank_money_from_akshare.py \
  --from-dump output/akshare-banks-2026-11-08.json \
  --cross-check output/bank-money-gta-banks-2026-11-08.json

# 离线单测（48 条）
../scraw-fd-open-data-mcp/.venv/bin/python -m pytest \
  test_bank_money_akshare.py test_bank_money_gta.py -q
```

注：`register_bank_money_from_akshare.py` 需同时具备 akshare 与 psycopg2，
`scraw-fd-open-data-mcp/.venv` 两者都有；`fd-open-data-mcp/.venv` 只有 psycopg2（够跑 GTA 侧）。

## 7. 回滚

```sql
-- 删金额指标观测（只影响这 4 个概念，不碰其他源）
delete from semantic_observations o using concepts c
where o.concept_id = c.id and o.source_used = 'akshare'
  and c.code in ('financials.customer_deposits','financials.net_interest_income',
                 'financials.fee_and_commission_income','financials.loans_and_advances_net');
-- 概念如需下线：update concepts set deprecated = true where code in (...)
```

## 8. 未决

- **季频观测**：akshare 有季报数据（工行到 2026-09-30），但把季频写进 `frequency=yearly`
  概念会重演「granularity 退化」的旧坑，故本期只登记年报，季度留待单独裁定。
- 逾期/重组类率指标披露面仅 6/42、11/42，是否纳入指标组未裁。
- 比率类监管指标（资本充足率等）仍只有 5 家（`cn-report` 口径）——扩覆盖属 B 线另一议题。

---

# 追加：银行监管比率的结构化源（2026-11-08，C 线阈值告警需要）

## 为什么又找一个源

阈值告警原先只覆盖 **5/42 家**——比率只来自 `cn-report` 的报告抽取（5 家试点）。
akshare 封装的财务指标接口都不带银行监管比率（`stock_financial_abstract_ths` /
`stock_financial_analysis_indicator` 实测无相关列，`..._em` 本身坏）。
但**东财 F10 原始接口有**，akshare 只是没封装。

## 源与字段

`RPT_F10_FINANCE_MAINFINADATA`（datacenter-web，`filter=(SECURITY_CODE="...")`；注意用
`SECUCODE` 会返回 0 行），165 个字段，本批银行可用 4 个：

| 指标 | 字段 | 概念码 | FY2025 抽查（601398） | golden |
|---|---|---|---|---|
| 资本充足率 | `NEWCAPITALADER` | `financials.capital_adequacy_ratio` | 18.76 | 18.76 ✓ |
| 一级资本充足率 | `FIRST_ADEQUACY_RATIO` | `financials.tier1_capital_adequacy_ratio` | 14.94 | 14.94 ✓ |
| 拨备覆盖率 | `BLDKBBL` | `financials.provision_coverage_ratio` | 213.60 | 213.60 ✓ |
| 贷款拨备率 | `LOAN_PROVISION_RATIO` | `financials.loan_loss_provision_ratio` | 2.79 | 2.79 ✓ |

**核对方式不是自证**：拿 harden 期从报告原文逐值核过的 golden 锚（5 家 × 4 项 = 20 点）
去比 FY2025 → **20/20 完全一致**；全量取数后 `--verify` 亦 `checked=15 mismatched=0 missing=0`。

## 明确排除的字段（口径对不上就不能用）

- `LIQUIDATION_RATIO`：601398 = **108.03**，而 golden 流动性比例 = **63.20** ⇒ 不是该指标
  （量级更像流动性匹配率，但接口不给中文名，**不猜、不映射**）
- `RCAPITAL_RATIO`（核心一级）/ `CAPITAL_LEVERAGE_RATIO`（杠杆率）/
  `LIQUIDITY_COVERAGE_RATIO`（LCR）：该来源对本批银行**恒为 null**，无值可用

## 落库与覆盖

- `bank_ratio_f10.py` + `scripts/register_bank_ratios_from_f10.py` + `test_bank_ratio_f10.py`（12 单测）
- 登记 **316 行** `source_used='eastmoney-f10'`，**20 行跳过**（5 家试点 2025 年已有 cn-report 值，
  保持「同一概念+主体+日期单源」）
- 覆盖：资本充足率 / 一级 / 拨备覆盖率 / 拨贷比 **5 家 → 42 家**（FY2024 与 FY2025 均 42）
- 告警侧：阈值判定 **30 条 → 104 条**，覆盖 **42/42**，全部合规（0 越线）；
  数值区间 11.62–19.69，量级正常

## 仍然只有 5 家的 4 项

核心一级资本充足率、杠杆率、流动性覆盖率、净稳定资金比例——F10 无值，
仍需报告抽取扩面（B 线议题）。**有数据和能判定是两件事**：拨备覆盖率/贷款拨备率
数据虽已 42 家，但规则因「区间 + 分档条件」仍停用。
