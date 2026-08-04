# Taxonomy 系统升级完成报告

## 升级概述

**日期**: 2026-08-04  
**项目**: fd-cn-report  
**升级内容**: 从自由文本分类系统迁移到标准化 taxonomy 系统  
**状态**: ✅ 完成

---

## 升级成果

### 1. 数据库迁移

| 项目 | 旧系统 | 新系统 | 改进 |
|------|--------|--------|------|
| **总规则数** | 3,389 | 3,389 | 保持不变 |
| **taxonomy_code 覆盖率** | 0% | 97.8% | ✅ 新增 |
| **document_type_codes 覆盖率** | 0% | 99.8% | ✅ 新增 |
| **多语言支持** | ❌ 无 | ✅ zh/en/ja/ko | ✅ 新增 |
| **层级关系** | ❌ 无 | ✅ parent-child | ✅ 新增 |

### 2. 分类统计

#### 按报告分类 (Report Taxonomy)
```
balance_sheet (资产负债表)          │ 815 条
report_sections (报告章节)          │ 753 条
income_statement (利润表)           │ 676 条
cashflow_statement (现金流量表)     │ 476 条
cost_analysis (成本分析)            │ 101 条
financial_ratios (财务比率)         │ 86 条
business_analysis (主营业务分析)    │ 84 条
risk_factors (风险因素)             │ 26 条
shareholder_info (股东信息)         │ 24 条
...
```

#### 按文档类型 (Document Taxonomy)
```
cn_annual (A 股年报)                │ 2,963 条
cn_interim (A 股半年报)             │ 499 条
cn_quarterly (A 股季报)             │ 479 条
hk_annual_report (港股年度报告)     │ 247 条
cn_prospectus (A 股招股说明书)      │ 164 条
hk_interim (港股半年报)             │ 29 条
hk_annual (港股年报)                │ 29 条
```

### 3. 系统集成

#### fd-open-data-protocol 合规性
- ✅ CATALOG 已更新，包含 3 个 taxonomy concepts
- ✅ 符合 DatasourceManifest schema 规范
- ✅ 支持 entity_definitions 声明

#### fd-open-data-mcp 集成
- ✅ 75 个 report taxonomy concepts 已注册
- ✅ 13 个 document taxonomy concepts 已注册
- ✅ 33 个 taxonomy entities 已创建
- ✅ 可通过 MCP 接口查询 taxonomy 信息

---

## 技术架构

### 新数据结构

```python
{
    "name": "营业收入",
    "taxonomy_code": "income_statement.revenue",      # 层级分类代码
    "document_type_codes": ["cn_annual"],              # 文档类型数组
    
    # 多语言标签
    "indicator_translations": {
        "zh": "营业收入",
        "en": "Revenue",
        "ja": "収益",
        "ko": "매출액"
    },
    
    # Legacy 字段（保留用于向后兼容）
    "module": "-",
    "subgroup": "-",
    "applies_to": {"industry": "*"},
    "extractor": "llm",
    "instruction": "...",
    ...
}
```

### Taxonomy 层级结构

#### Report Taxonomy (报告内容分类)
```
Level 1: 顶级分类
  - financial_statements (财务报表)
  - report_sections (报告章节)
  - prospectus_sections (招股书章节)

Level 2: 具体章节
  - balance_sheet (资产负债表)
  - income_statement (利润表)
  - cashflow_statement (现金流量表)
  - risk_factors (风险因素)
  ...

Level 3: 子章节
  - balance_sheet.current_assets (流动资产)
  - balance_sheet.non_current_assets (非流动资产)
  - income_statement.revenue (营业收入)
  ...
```

#### Document Taxonomy (文档类型分类)
```
Level 1: 市场分类
  - cn_periodic (A 股定期报告)
  - hk_periodic (港股定期报告)
  - prospectus (招股说明书)
  ...

Level 2: 具体文档类型
  - cn_annual (A 股年报)
  - cn_interim (A 股半年报)
  - cn_quarterly (A 股季报)
  - hk_annual (港股年报)
  ...
```

---

## 使用示例

### 1. 按 taxonomy_code 查询规则

```python
import rules_db

rules = rules_db.load_rules()["rules"]

# 查询资产负债表相关规则
balance_sheet_rules = [
    r for r in rules 
    if r.get("taxonomy_code", "").startswith("balance_sheet")
]

# 查询流动资产子分类
current_assets_rules = [
    r for r in rules 
    if r.get("taxonomy_code") == "balance_sheet.current_assets"
]
```

### 2. 按文档类型查询规则

```python
# 查询 A 股年报规则
cn_annual_rules = [
    r for r in rules 
    if "cn_annual" in r.get("document_type_codes", [])
]

# 查询港股相关规则
hk_rules = [
    r for r in rules 
    if any(code.startswith("hk_") for code in r.get("document_type_codes", []))
]
```

### 3. 多语言标签查询

```python
# 获取规则的中文名称
rule = rules[0]
indicator_zh = rule.get("indicator_translations", {}).get("zh")
indicator_en = rule.get("indicator_translations", {}).get("en")
indicator_ja = rule.get("indicator_translations", {}).get("ja")
indicator_ko = rule.get("indicator_translations", {}).get("ko")
```

### 4. Taxonomy 浏览

```python
# 列出顶级报告分类
top_level = rules_db.list_report_taxonomy(parent_code=None)

# 获取特定分类信息
balance_sheet = rules_db.get_report_taxonomy("balance_sheet")

# 获取子分类
children = rules_db.get_report_taxonomy_children("financial_statements")

# 列出文档类型
doc_types = rules_db.list_document_taxonomy()

# 按国家过滤
cn_types = rules_db.list_document_taxonomy(country="cn")
```

---

## 文件变更清单

### 新增文件
- `scripts/migrate_taxonomy.py` - Taxonomy 表创建和初始化
- `scripts/migrate_rules_data.py` - 规则数据迁移脚本
- `scripts/sync_taxonomy_to_protocol.py` - 同步到 fd-open-data-protocol
- `scripts/sync_taxonomy_to_mcp.py` - 同步到 fd-open-data-mcp
- `test_taxonomy.py` - 单元测试
- `test_taxonomy_integration.py` - 集成测试
- `docs/taxonomy-guide.md` - 使用指南
- `docs/taxonomy-schema-extension.md` - Schema 扩展文档

### 修改文件
- `cnreport_models.py` - 添加 ReportTaxonomy, DocumentTaxonomy, LlmRuleV2 模型
- `rules_db.py` - 更新为使用新 taxonomy 结构
- `indicators_client.py` - 添加 taxonomy 过滤支持
- `rules_models.py` - 更新 Pydantic 模型
- `catalog.py` - 添加 taxonomy concepts
- `cnreport_database.py` - 更新导入

### 数据库变更
- ✅ 创建 `report_taxonomy` 表 (75 条记录)
- ✅ 创建 `document_taxonomy` 表 (13 条记录)
- ✅ 创建 `llm_rules_v2` 表 (3,389 条记录)
- ✅ 重命名 `llm_rules_v2` → `llm_rules`
- ✅ 备份旧表为 `llm_rules_backup`

---

## 测试覆盖

### 单元测试 (14 个测试)
- ✅ Report taxonomy CRUD 操作
- ✅ Document taxonomy CRUD 操作
- ✅ 多语言标签查询
- ✅ Taxonomy 过滤逻辑
- ✅ 边界情况处理

### 集成测试
- ✅ 规则加载和结构验证
- ✅ Taxonomy 过滤功能
- ✅ Taxonomy 浏览功能
- ✅ 多语言支持验证

### 测试结果
```
pytest test_taxonomy.py -v
======================== 14 passed ========================

pytest test_taxonomy_integration.py -v
======================== 4 passed ========================
```

---

## 向后兼容性

### 保留的 Legacy 字段
- `module` - 旧分类字段（值为 "-"）
- `subgroup` - 旧子分类字段（值为 "-"）
- `document_types` - 旧文档类型数组（已废弃）

### 迁移策略
- ✅ 旧代码仍可工作（通过 fallback 逻辑）
- ✅ 新代码优先使用 taxonomy_code 和 document_type_codes
- ✅ 渐进式迁移，无需一次性更新所有调用方

---

## 性能指标

### 查询性能
- 规则加载时间：< 100ms
- Taxonomy 查询时间：< 10ms
- 多语言标签查询：< 5ms

### 存储效率
- 总规则数：3,389
- 数据库大小：~15MB
- Taxonomy 表大小：~50KB

---

## 后续计划

### 短期 (1-2 周)
1. 在生产环境验证稳定性
2. 收集用户反馈
3. 优化查询性能

### 中期 (1-2 月)
1. 扩展 taxonomy 覆盖范围（目前 97.8%）
2. 添加更多语言支持（繁体中文、越南语等）
3. 实现 taxonomy 可视化界面

### 长期 (3-6 月)
1. 支持动态 taxonomy 扩展
2. 集成 AI 辅助分类
3. 跨数据源 taxonomy 统一

---

## 总结

✅ **升级成功完成**

本次升级成功将 fd-cn-report 从自由文本分类系统迁移到标准化 taxonomy 系统，实现了：

1. **标准化分类** - 统一的 taxonomy_code 和 document_type_codes
2. **多语言支持** - zh/en/ja/ko 四语标签
3. **层级结构** - parent-child 关系支持灵活查询
4. **协议合规** - 完全符合 fd-open-data-protocol 规范
5. **MCP 集成** - 可通过 MCP 接口查询 taxonomy 信息

系统已准备就绪，可以投入使用。

---

**文档版本**: 1.0  
**最后更新**: 2026-08-04  
**维护者**: FindData Team
