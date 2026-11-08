# 银行 scoped 规则盘点：在册 ≠ 可用

- 生成：2026-11-08（`scripts/bank_rule_inventory.py`）
- 范围：13 个 bank-scoped 指标的全部 13 行
- 关键：`resolve_rule()` **每个指标只返回一行**，表中「选中」列才是真正生效的那一行

| id | 指标 | source | applies_to | resolve_rule 选中 | 判定 |
|---|---|---|---|---|---|
| 83 | 不良率 | formula | 双层:bank | ✓ | 非报告口径 |
| 643 | 净利息收入 | statement | 双层:bank | ✓ | 非报告口径 |
| 904 | 发放贷款及垫款 | selectors | 双层:bank | ✓ | 可修（休眠：applies_to 双层） |
| 1300 | 客户存款 | selectors | 双层:bank | ✓ | 可修（休眠：applies_to 双层） |
| 1670 | 手续费及佣金净收入 | statement | 双层:bank | ✓ | 非报告口径 |
| 1835 | 拨贷比_coverage | formula | 双层:bank | ✓ | 非报告口径 |
| 2336 | 流动性比例（人民币） | selectors | 单层:bank | ✓ | 可用 |
| 2959 | 质押贷款净增加额 | statement | 双层:bank | ✓ | 非报告口径 |
| 3038 | 贷款和垫款总额 | selectors | 双层:bank | ✓ | 可修（休眠：applies_to 双层） |
| 3156 | 逾期90天重组贷款率 | selectors | 双层:bank | ✓ | 可修（休眠：applies_to 双层） |
| 3158 | 逾期贷款率 | selectors | 双层:bank | ✓ | 可修（休眠：applies_to 双层） |
| 3199 | 重组贷款率 | selectors | 双层:bank | ✓ | 可修（休眠：applies_to 双层） |
| 3377 | 风险加权资产合计 | selectors | 双层:bank | ✓ | 可修（休眠：applies_to 双层） |

判定分布：{"非报告口径": 5, "可修（休眠：applies_to 双层）": 7, "可用": 1}
