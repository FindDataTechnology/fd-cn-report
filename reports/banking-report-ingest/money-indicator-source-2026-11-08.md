# 金额类银行指标：结构化源落档（2026-11-08）

配套 change：`bank-indicator-money-unit-support`。本文是**盘点面**——12 项历史休眠指标的
「能取 / 不能取、为什么、从哪取」，下一个人不用再摸一遍。

## 1. 结论一句话

金额类指标**不在报告正文解析单位**（四次证伪），改由 windows-admin 的 **GTA 面板**
（`gta_panel`，只读角色 `fdbiz_ro`）取值：值统一为**元**，42 家银行 FY2019–FY2024 已登记
**966 行**观测。面板**滞后一个财年**（FY2025 全空），故最新财年仍缺。

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

真源：`fd-cn-report/docs/bank-money-indicator-sources.json`（含逐条原文证据）。

### 2.1 命名规则（会绊人的一处）

`indicator_zh` **必须与 `daas.db` 的 `llm_rules.indicator` 同名**——那是引擎、盘点与 spec 的联结键。
实测撞点：面板标签叫「**利息**净收入」，规则库叫「**净**利息收入」，按名 join 会把这一项静默丢掉；
现以规则库名字为规范名，面板叫法降为 `aliases`，摄入时自动归一（`accepted_names()`）。

`流动性比例（人民币）`不在这张表里，因为它走比率抽取路径且已 5/5 精确（不在金额项之列）。

## 3. 口径陷阱（最重要的一节）

**面板是资产负债表账面口径，含应计利息。** 报告前部的「客户存款总额」「各项贷款」是**本金**
口径。混用差约 1%，且这正是 `harden-bank-indicator-rules` 期错值的形态之一。

两处独立加总实证（证据取自年报原文，**不是**从面板反抄）：

- 招行 FY2024 存款：本金 `9,096,587` + 应计利息 `98,742` = **`9,195,329`** 百万元 = 面板值
  （FY2023 同法：`8,155,438` + `85,060` = `8,240,498` = 面板值）
- 工行 FY2024 贷款：总额 `28,372,229` + 应计利息 `56,624` − 减值准备 `815,072` = 净额 **`27,613,781`** 百万元 = 面板值

由此定死两条：
1. `客户存款` = 含应计利息口径；观测行带 `caliber` 说明。
2. `发放贷款及垫款` = **净额**，名称与口径都不得写「总额」。

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

（42 家银行样本内非空家数。FY2025 整列为空 ⇒ 脚本以 `{"reason":"source_empty"}` 留痕，
**不插值、不用 FY2024 顶替**。）

## 5. 已落库数据

- 概念：`financials.customer_deposits` / `financials.net_interest_income` /
  `financials.fee_and_commission_income` / `financials.loans_and_advances_net`（均 `verified=True`，
  `unit=currency`，`frequency=yearly`）→ `financials` 概念总数 55 → **59**
- 观测：**966 行**，`source_used='gta-panel'`，date 形如 `YYYY-12-31`，`granularity='year'`
- 幂等：复跑 `inserted=0 skipped=966`
- 读数面实弹：pod 内回读工行 FY2024 存款 = `34836973000000 currency gta-panel`，实体解析到 `entity_id=59`

## 6. 复核命令

```bash
# 取数 + 核锚（锚的证据取自年报原文，不一致非零退出）
cd fd-cn-report
FDBIZ_DOMAIN_PG_URL="$(grep '^FDBIZ_DOMAIN_PG_URL=' ../fd-find-data-business-mcp/.env | cut -d= -f2-)" \
  ../fd-open-data-mcp/.venv/bin/python scripts/register_bank_money_from_gta.py \
  --years 2019-2025 --dump output/bank-money-gta-banks-2026-11-08.json --verify

# 离线单测
../fd-open-data-mcp/.venv/bin/python -m pytest test_bank_money_gta.py -q
```

## 7. 回滚

```sql
delete from semantic_observations where source_used = 'gta-panel';   -- 删观测
-- 概念如需下线：update concepts set deprecated = true where code like 'financials.%'
--   and code in ('financials.customer_deposits', ...)
```

## 8. 未决

- FY2025 及以后的金额指标取数路径：等面板入库（脚本可直接续跑，不改码），或在
  `fd-cn-report` 恢复抽取后单走报告路径——受「线上保持只读」裁定（11-08）约束，当前悬置。
- 逾期/重组类率指标披露面仅 6/42、11/42，是否纳入指标组未裁。
