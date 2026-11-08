# 全库 `applies_to` 双重编码影响面（干跑，未落库）

- 生成：2026-11-08　数据源：finddata/daas.db `llm_rules`（共 3392 行）
- 现状：**3370 行仍是双层 JSON 编码**，读取面（`to_rule_dict`）只解一层 → `applies_to()` 只放行
  `"*"/"null"/"None"` → 所有**带行业范围**的规则被静默判「不适用」（本 change 只降层了银行 22 行）。

## 修复后行为会发生变化的规则（25 条）

判据：内层 `industry` ∉ {null, "*"} 的行——修好后它们会**从「静默不适用」变为「按行业范围生效」**。

| 行业 | 行数 | 指标 |
|---|---|---|
| bank | 13 | 不良率、净利息收入、发放贷款及垫款、客户存款、手续费及佣金净收入、拨贷比_coverage、流动性比例（人民币）、质押贷款净增加额、贷款和垫款总额、逾期90天重组贷款率、逾期贷款率、重组贷款率、风险加权资产合计 |
| insurance | 11 | 保单红利支出、保户储金及投资款净增加额、保险合同赔付支出、分保费用、已赚保费、提取保险责任准备金净额、支付保单红利的现金、支付原保险合同赔付等款项的现金、收到再保险业务现金净额、收到原保险合同保费取得的现金、退保金 |
| securities | 1 | 代理买卖证券收到的现金净额 |

其余 3345 行内层行业是 `null`/`*`（全行业），修前修后行为一致，纯属编码整洁问题。

## 建议

1. 先跑一次 `--dry-run` 并备份（`output/bank-rules/`），再按 `WHERE indicator IN (...)` 分批降层；
2. 降层后**必须复跑**各行业既有 golden/consistency 检查——那 25 条会首次真正生效；
3. 保险 11 条与证券 1 条属其他条线，宜由相应条线会话确认后再改（避免并发会话行为漂移）。

复算：`python3 - <<'EOF'` 读 `llm_rules.applies_to`，对每行 `json.loads` 两次，内层为 dict 且
`industry` ∉ {null,"*"} 即计入。

## 实弹尝试与回滚（2026-11-08 05:50，重要）

按「只修银行 13 行」实跑了一遍 `scripts/repair_applies_to_encoding.py --scope bank`，**然后回滚了 applies_to**。原因是一条链式的第二层/第三层缺陷：

1. 降层 `applies_to` 后这 13 条**真的进了 applicable**（实测 601398 命中 6/6 抽检项）——这一步是成功的；
2. 但立刻崩：`AttributeError: 'str' object has no attribute 'get'`（`_resolve_via_akshare` 的 `src.get("statement")`）——**`source` 列也是双层**；
3. 把 `source/aliases/value_range` 一起降层后再跑，又崩 `'NoneType' object has no attribute 'get'`（`_resolve_section` 的 `src.get("selectors")`）——有些行的 `source` **字面是 `null`**。

也就是说这 13 条规则**从来没能工作过**（双层 applies_to 让它们休眠，掩盖了 source 的三种坏形态）：

| 形态 | 条数 | 表现 | 要修什么 |
|---|---|---|---|
| `source` 有 selectors | 8 | 可直接按报告抽取 | 需要像 17 项那样逐指标调选择器 + 逐值核对 |
| `source` 是 formula/statement（akshare 口径，`inputs`/`statement`+`field`） | 4 | 报告 PDF 抽不出，走 akshare 旁路 | 要么改写成报告选择器，要么明确标为「不走报告」 |
| `source` 字面 `null` | 1+ | 直接抛异常 | 补 selectors 或删规则 |

**当前状态**：`applies_to` 已回滚为双层（休眠）；`source/aliases/value_range` 保持已降层（编码正确，休眠下无害）。备份：
`output/bank-rules/applies-to-bank-20261108-055001.json`（applies_to 原值）、`-055116.json`（四列原值）。

回滚后复核：601398 的 `杠杆率 7.51 / 拨备覆盖率 213.6 / 资本充足率 18.76` 抽取正常，17 项 golden 不受影响。

**另有一处既有隐患（与本次降层无关）**：`发放贷款及垫款`、`客户存款`、`手续费及佣金净收入`、`质押贷款净增加额`
这 4 个指标有 `applies_to` 为**字面 `null`** 的行（读取面按"全行业"放行），其中多数行 `source` 也是字面 `null` →
**显式请求这几个指标会抛异常**（降层前后都一样，属既有缺陷）。修法同上：补 selectors 或清掉这些空壳行。

**结论**：全库降层不是一条 SQL 的事，正确顺序是「先让 13 条规则各自可用（选择器/口径/逐值核），再降 applies_to」。
建议单独立项 `harden-bank-indicator-rules`，把这 13 条按 17 项同一套流程（选择器链 + note + golden 锚）补齐后再启用。
