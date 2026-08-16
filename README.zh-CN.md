# fd-cn-report

[English](README.md) | **中文**

面向中国财务报告的 MCP 服务器 —— 覆盖 31 个申万 L1 行业的 AI 规则系统、
目录提取、AI 结构化抽取、Elasticsearch 存储与检索，以及交互式规则看板。

## 行业规则系统

**21,698 条 LLM 规则**，覆盖 **31 个申万 L1 行业**，每条规则记录某个指标在
定期报告中的精确章节位置，提取指令由真实年报 PDF 生成。

### 覆盖范围

| 章节 | 内容 | 说明 |
|------|------|------|
| 资产负债表 | 全部科目 (112+ rules) | 从合并资产负债表提取 |
| 利润表 | 全部科目 (130+ rules) | 从合并利润表提取 |
| 现金流量表 | 全部科目 (42+ rules) | 从合并现金流量表提取 |
| 管理层讨论 | 主营业务分析、成本、产销量、研发 | 从实际报告第三节提取 |
| 主要财务指标 | ROE、EPS、毛利率、分季度数据 | 从第二节提取 |
| 报表附注/重要事项 | 关联交易、担保、诉讼、资产减值 | 从第六节+第十节附注提取 |
| 股东信息 | 前十大股东、持股变动、分红 | 从第七节提取 |
| 公司治理 | 董事会、高管薪酬 | 从第四节提取 |
| 环境 | 排污、碳排放、能源消耗 | 从第五节提取 |

### 行业特有规则

6 个行业在通用规则集之上额外拥有行业特有规则：

| 行业 | 特有指标 | 来源 |
|------|---------|------|
| 银行 | 不良率、净息差、资本充足率、贷款五级分类 | 工商银行年报 |
| 房地产 | 合同负债、存货-开发成本、土储、销售面积 | 保利发展年报 |
| 电力设备 | 在建工程、产能利用率、应收账款 | 宁德时代年报 |
| 医药生物 | 研发费用、销售费用、在研管线、无形资产 | 恒瑞医药年报 |
| 非银金融 | 保费收入、赔付支出、偿付能力、新业务价值 | 中国平安年报 |
| 农林牧渔 | 存货-消耗性生物资产 | 隆平高科年报 |

### 规则生成流水线

规则由真实年报 PDF 经并行 LLM 调用生成：

```bash
# 从真实报告为全部 31 个行业生成规则
python scripts/generate_rules_from_real_reports.py --max-concurrent 5

# 单个行业
python scripts/generate_rules_from_real_reports.py --industry 801120

# 仅运行行业特有章节
python scripts/generate_rules_from_real_reports.py --industry 801780 --llm-only
```

### 看板

用于浏览、筛选、检索全部 21,698 条规则的交互式 Web 界面：

```bash
# CLI
python scripts/industry_rules_dashboard.py
# 或
fd-cn-report

# MCP 工具
open_industry_rules_dashboard(port=8888)
```

功能：
- **行业筛选** —— 含全部 31 个申万 L1 行业的下拉框
- **模块筛选** —— 按资产负债表、利润表等筛选
- **关键词检索** —— 指标名、章节、指令文本
- **可排序列** —— 点击表头排序
- **分页** —— 每页 50 条规则
- **颜色标签** —— 模块类型可视化
- **实时统计** —— 筛选后的数量、行业数、模块数

---

## 工具（44 个 MCP 工具）

| 层 | 工具 | 说明 |
|-------|------|-------------|
| **公司 API** | `get_company` | 代码/名称 → 公司条目 |
| | `list_filings` | 按公告类型/类别 + 年份列出 CNINFO 披露 |
| | `get_filing` | 单条公告的元数据 + PDF URL |
| | `get_financials` | 经 akshare 获取利润表/资产负债表/现金流量表 |
| | `get_financial_statements` | 从年报 PDF 以文本形式提取三大报表 |
| | `get_section` | `(代码, 年份, 章节)` → 章节文本 |
| | `list_report_types` | 浏览 CNINFO 披露类别目录 |
| | `get_special_report` | 特殊类型报告（招股说明书、收购报告书等） |
| **港股** | `get_hk_company` | 按代码/名称解析港股 |
| | `list_hk_filings` | 列出 HKEX 披露 |
| | `get_hk_financials` | 港股财务报表 |
| | `get_hk_section` | 港股报告章节提取 |
| **交易所官网（上交所/深交所/北交所）** | `get_sse_company` | 按 6 位代码解析上交所上市公司 |
| | `list_sse_filings` | 从 sse.com.cn 列出上交所披露 |
| | `get_sse_section` | 上交所年报章节提取 |
| | `get_sse_interaction` | 上证e互动 投资者问答 |
| | `get_szse_company` | 按 6 位代码解析深交所上市公司 |
| | `list_szse_filings` | 从 szse.cn 列出深交所披露 |
| | `get_szse_section` | 深交所年报章节提取 |
| | `get_szse_interaction` | 互动易 投资者问答 |
| | `get_bse_company` | 按 6 位代码解析北交所上市公司 |
| | `list_bse_filings` | 列出北交所披露（北交所原生，缺失则回退 CNINFO） |
| | `get_bse_section` | 北交所年报章节提取 |
| **证监会** | `list_csrc_filings` | 列出证监会监管公告 |
| | `get_csrc_ipo_review` | 证监会首发审核状态 |
| | `get_csrc_merger_review` | 证监并购重组审核状态 |
| | `list_csrc_enforcement` | 证监会行政处罚 |
| **部委统计** | `list_ministries` | 列出支持的部委统计源 |
| | `get_ministry_stat` | 部委统计页面 → HTML 表格 |
| | `get_nbs_stat` | 按指标代码获取统计局宏观统计 |
| **PDF / AI / ES** | `list_outline` | 从报告 URL 或 PDF 路径解析目录 |
| | `extract_section` | 按精确标题/正则/序号取正文 |
| | `ai_extract` | 对章节文本做 LLM 结构化抽取 |
| | `index_records` | 批量将记录索引入 ES |
| | `search_reports` | BM25 + 过滤检索（带高亮） |
| | `delete_index` | 删除 `cnreport-{year}` 索引 |
| **缓存** | `list_cache` | 列出已缓存报告 |
| | `clear_cache` | 清除已缓存报告 |
| **指标** | `list_indicators` | 浏览指标规则集 |
| | `get_indicator` | 取单个指标的值 |
| | `extract_indicators` | 一次取所有适用指标 |
| | `extract_indicators_by_position` | CSV 驱动抽取 |
| | `audit_rule_gaps` | 审计各行业/各代码缺失的规则 |
| **看板** | `open_industry_rules_dashboard` | 启动规则 Web 看板 |

> `extract_indicators_batch` 是一个 **Python 便捷函数**（非 MCP 工具） ——
> 见[并发](#并发)。

## 典型链路

```python
# 1. 解析公司 → 2. 查最新年报 → 3. 取 MD&A → 4. LLM 抽取营收表

co = get_company("600519")
# {"stock_code": "600519", "name": "贵州茅台", "org_id": "gssh0600519", "exchange": "sse", ...}

filings = list_filings("600519", form="年度报告", year=2023, limit=3)
# [{"announcement_id": "1219730876", "pdf_url": "http://static.cninfo.com.cn/.../*.PDF", ...}]

sec = get_section("600519", year=2023, section="管理层讨论与分析")
# {"text": "<MD&A 全文>", "pdf_url": "...", "outline_entry": {...}, ...}

records = ai_extract(
    text=sec["text"],
    schema={"type": "object", "properties": {
        "segment": {"type": "string"},
        "revenue_2023": {"type": "string"},
    }, "required": ["segment", "revenue_2023"]},
)
# {"records": [{"segment": "茅台酒", "revenue_2023": "139,989,000,000"}, ...]}
```

## 特殊报告类型

除四类定期报告外，CNINFO 还暴露数十个披露类别（招股说明书、增发、业绩预告、
收购报告书、股权激励等）。先浏览目录，再按类别列出或获取：

```python
catalog = list_report_types()
# {"groups": [{"name": "定期报告", "categories": [...]}, {"name": "融资", ...}, ...], "count": 26}

list_report_types(group="融资")
# {"group": "融资", "categories": [{name: "首发", code: "category_sf_szsh", ...}, ...], "count": 6}

filings = list_filings("600519", category="首发", limit=3)

sec = get_special_report("600519", category="首发", section="募集资金运用")
```

## 三大报表

`get_financials` 返回 akshare 的结构化数值表。`get_financial_statements`
从 PDF 中以**文本**形式提取三大报表章节：

```python
stmts = get_financial_statements("600519", year=2023)
# {
#   "stock_code": "600519", "company_name": "贵州茅台", "year": 2023,
#   "form": "年度报告", "pdf_url": "...", "cached": False,
#   "statements": {
#     "income_statement": {"title": "2、 合并利润表", "outline_entry": {...}, "char_count": 4521, "text": "..."},
#     "balance_sheet":    {"title": "1、 合并资产负债表", ...},
#     "cashflow":         {"title": "3、 合并现金流量表", ...},
#   },
#   "missing": [],
# }
```

## 报告缓存

每次报告抓取都经过 `.cache/reports/` 下的磁盘缓存。首次抓取下载 PDF 并提取
文本 + 目录；后续抓取从磁盘读取。

```python
list_cache()
# {"cache_dir": ".../.cache/reports", "count": 2, "entries": [...]}

clear_cache()                              # 清除全部
clear_cache(stock_code="600519")           # 清除单个公司
clear_cache(stock_code="600519", year=2023) # 清除单个公司 + 年份
```

## 指标

指标引擎对每个公司画像，筛选适用规则，并将每条指标路由到
akshare / 报告章节 / 计算 / 外部。

```python
# 预览 → 取单个 → 取全部 → CSV
list_indicators(company="工商银行")           # 工商银行适用的规则
get_indicator("资本充足率", "工商银行", 2023)  # 单个值
extract_indicators("工商银行", 2023)           # 所有适用指标，一次 PDF 抓取
extract_indicators("工商银行", 2023,
                   indicators=["资本充足率","不良率"])  # 子集
extract_indicators("工商银行", 2023, extractor_mode="python")  # 不用 LLM
extract_indicators_by_position("工商银行", 2023)  # CSV 驱动
```

多报告类型支持（年度报告 / 半年度报告 / 第一季度报告 / 第三季度报告）：

```python
extract_indicators_by_position("工商银行", 2023, form="第一季度报告")
extract_indicators("贵州茅台", 2023, form="半年度报告")
```

### 并发

```python
extract_indicators("工商银行", 2023, concurrency=4)  # 显式上限
extract_indicators("工商银行", 2023, concurrency=1)  # 顺序执行

# 批量：多公司并发抽取
extract_indicators_batch([("601398", 2023), ("600519", 2023)],
                         concurrency=2, extract_concurrency=4)
# → {"results": {"601398_2023": {...}, ...}, "failures": [...], "concurrency": 2}
```

### 章节缓存

LLM 响应持久化到磁盘，键为 `(pdf_url, section_key, period, rules_hash)`。
后续运行复用缓存记录。设 `LLM_SECTION_CACHE=off` 可禁用。

## 独立 CLI

```bash
# 完整引擎抽取
python scripts/extract_indicators.py 601398 --year 2023 \
    [--rules indicator_rules.json] [--extractor auto|llm|python] \
    [--indicators 资本充足率,不良率] [--out-dir ./out]

# CSV 驱动抽取
python scripts/extract_indicators_by_position.py 601398 --year 2023 \
    [--csv docs/indicators_position.csv] [--extractor auto|llm|python] \
    [--form 年度报告|半年度报告|第一季度报告|第三季度报告]

# 多年抽取
python scripts/extract_indicators_multiyear.py 601398 2023 2024

# 行业规则看板
python scripts/industry_rules_dashboard.py [port]
# 或：fd-cn-report

# 从真实报告生成行业规则
python scripts/generate_rules_from_real_reports.py

# 检查行业覆盖
python scripts/check_industry_coverage.py

# 播种行业规则
python scripts/seed_industry_rules.py
```

## 港股支持

```python
get_hk_company("00700")                    # → 腾讯控股
list_hk_filings("00700", year=2023)        # → HKEX 披露
get_hk_financials("00700")                 # → 财务报表
get_hk_section("00700", year=2023, section="管理层讨论与分析")
```

## 交易所官网数据源（上交所/深交所/北交所）

直连交易所的一手披露路径，作为 CNINFO 的补充。每个交易所客户端本地解析 6 位
代码（无需联网），并从交易所自身站点列出披露。当北交所自有 API 数据较薄时
回退到 CNINFO，每行带 `source: "bse" | "cninfo"` 标记。章节提取复用与
CNINFO/港股相同的目录流水线。

```python
# 上交所 - 600/601/603/605/688/900 代码段
get_sse_company("600519")
list_sse_filings("600519", year=2023)                         # -> sse.com.cn 披露
get_sse_section("600519", year=2023, section="管理层讨论与分析")
get_sse_interaction("600519")                                  # -> 上证e互动 问答

# 深交所 - 000/001/002/003/300/301 代码段
get_szse_company("000001")
list_szse_filings("000001", year=2023)                        # -> szse.cn 披露
get_szse_section("000001", year=2023, section="管理层讨论与分析")
get_szse_interaction("000001")                                 # -> 互动易 问答 (irm.cninfo.com.cn)

# 北交所 - 430xxx / 83xxxx / 87xxxx / 88xxxx / 920xxx 代码段
get_bse_company("835185")
list_bse_filings("835185", year=2023)                         # -> 北交所原生，缺失则回退 CNINFO
get_bse_section("835185", year=2023, section="管理层讨论与分析")  # 结果带 `source`
```

> **接口无官方文档。** 上交所（`query.sse.com.cn`）、深交所（`www.szse.cn/api`）、
> 北交所（`www.bse.cn`）及问答站点（`sns.sseinfo.com`、`irm.cninfo.com.cn`）
> 均未公开 API 契约，且会随时间变化。客户端实现轻量，对 429/5xx 重试，并绕过
> 代理环境变量（`trust_env=False`）。运行
> `CNREPORT_SELFCHECK_LIVE=1 uv run python selfcheck.py` 逐个探测接口 ——
> 4xx/5xx 按来源标记但不导致整套自检失败。这些客户端不支持按名称片段解析；
> 先用 `get_company`（CNINFO）解析名称，再传入 6 位代码。

## 证监会监管数据

CNINFO/交易所未覆盖的证监会监管数据：公告、首发/并购重组审核状态、行政处罚。
用 `lxml` 解析 HTML；接口无官方文档。

```python
list_csrc_filings(begin_date="2024-01-01")              # -> 监管公告
get_csrc_ipo_review("贵州茅台")                          # -> 首发审核状态行
get_csrc_merger_review("某科技股份公司")                 # -> 并购重组审核状态行
list_csrc_enforcement()                                 # -> 行政处罚
```

## 部委统计

来自部委级部门的结构化经济/金融统计，以*数据*查询补充 `fd-cn-gov` 的目录归档
抓取。统计局有 JSON API；其余发布 HTML 表格。结果在 `.cache/stats/` 下做 TTL
缓存。Base URL 在可引入时复用 `fd-cn-gov` 的注册表。

```python
list_ministries()                       # -> [{id, label, en, transport, base}, ...]
get_nbs_stat("A0201")                   # -> 统计局 GDP 序列 {period: value}  (dbcode="hgnd" 年度)
get_ministry_stat("gacc")               # -> 海关总署贸易页面解析为 HTML 表格
get_ministry_stat("pboc", limit=20)     # -> 央行货币表格
# 支持的 id: nbs mof pboc safe gacc nfra
```

> 部委统计页面路径与证监会 URL 均为推测且**无官方文档** ——
> 用 `CNREPORT_SELFCHECK_LIVE=1 uv run python selfcheck.py` 在线验证。
> 修正只需在 `ministry_stats_client._MINISTRIES` / `csrc_client._URLS`
> 中改一行。

## 安装

```bash
uv sync                    # 安装 akshare、pypdf、fastmcp 等
uv run python server.py    # FastMCP over stdio
```

自检（无网络）：

```bash
uv run python selfcheck.py           # 数据库 + 目录 + 公司 API + 特殊报告
uv run python selfcheck_cache.py     # 报告缓存 + 三大报表提取
```

测试（离线）：

```bash
uv run --with pytest python -m pytest test_cnreport.py -v -p no:logfire
```

## 配置

CNINFO 与 akshare **无需密钥**。其余工具需在 `.env` 中配置环境变量：

| 变量 | 使用方 | 是否必需 |
|-----|---------|-----------|
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | `ai_extract`、规则生成 | AI 功能必需 |
| `ES_URL`（+ 可选 `ES_API_KEY` 或 `ES_USERNAME`/`ES_PASSWORD`） | `index_records`、`search_reports`、`delete_index` | ES 功能必需 |
| `DAAS_DATABASE_URL` | provenance 写入、规则存储 | 默认 `daas.db` |
| `CNREPORT_CACHE_DIR` | 报告缓存 | 默认 `.cache/reports/` |
| `CNREPORT_SAVE_DIR` | PDF 本地保存（可选） | 可选 |
| `MINIO_*`（`MINIO_UPLOAD_ENABLED=true` 开启） | PDF 上传至 MinIO | 可选 |
| `LLM_SECTION_CACHE` | LLM 章节缓存开关 | 默认开启；`off` 禁用 |

## 架构

```
fd-cn-report/
├── server.py                      # FastMCP 服务（@app.tool 注册）
├── cninfo_client.py               # CNINFO API（无密钥查询）
├── hk_stock_client.py             # 港股 API（akshare + HKEX）
├── financials_client.py           # akshare 财务报表（懒加载）
├── cnreport_tools.py              # 纯函数辅助（目录、提取、LLM、ES）
├── report_cache.py                # 磁盘 PDF + 文本 + 目录缓存
├── llm_section_cache.py           # LLM 响应章节缓存
│
├── indicators_client.py           # 规则引擎（加载、画像、路由、提取）
├── indicators_extractors.py       # 可插拔 Python 抽取器
├── indicators_models.py           # Pydantic 抽取模型
├── indicators_csv_migration.py    # CSV → JSON 规则迁移
├── report_section_map.py          # 章节别名展开 + 匹配
│
├── rules_db.py                    # 规则数据库（SQLite via SQLAlchemy）
├── rules_models.py                # Pydantic 规则模型
├── rules_skills.py                # LLM 规则生成 + 校验
├── cnreport_models.py             # ORM 模型（LlmRule, ScriptRule）
├── cnreport_database.py           # 数据库连接管理
│
├── industry_taxonomy.py           # 申万 L1 行业分类
├── industry_coverage.py           # 行业规则覆盖检查
│
├── docs/
│   ├── industry_taxonomy.json     # 31 个行业分类
│   ├── industry_indicator_baseline.json  # 各行业基线指标
│   ├── indicators_position.csv    # 指标目录（CSV 源）
│   └── indicators-methodology.md  # 渲染的方法论
│
├── scripts/
│   ├── industry_rules_dashboard.py          # Web 看板（CLI + MCP）
│   ├── generate_rules_from_real_reports.py  # 分行业规则生成
│   ├── generate_all_industry_rules.py       # LLM 规则生成
│   ├── seed_industry_rules.py               # 通用规则播种
│   ├── seed_missing_industry_rules.py       # 行业特有规则播种
│   ├── extract_indicators.py                # 独立抽取 CLI
│   ├── extract_indicators_by_position.py    # CSV 驱动抽取 CLI
│   ├── extract_indicators_multiyear.py      # 多年批量抽取
│   ├── check_industry_coverage.py           # 覆盖校验
│   ├── migrate_indicators_csv.py            # CSV → DB 迁移
│   └── rules_dashboard.py                   # indicator_rules.json 编辑器
│
└── .cache/reports/                # 下载的 PDF + 提取的文本 + 目录
```

## 新增行业

1. 在 `docs/industry_taxonomy.json` 中添加：
   ```json
   {"industry": "801xxx", "label": "行业名称", "report_kinds": ["annual-report", "interim-report", "quarterly-report"]}
   ```

2. 在 `docs/industry_indicator_baseline.json` 中添加基线指标：
   ```json
   {"cn/801xxx/listed/annual-report": ["资产总计", "营业收入", "净利润", ...]}
   ```

3. 在 `scripts/generate_rules_from_real_reports.py` 中添加代表公司：
   ```python
   "801xxx": ("600xxx", "代表公司", "行业名称"),
   ```

4. 定义行业特有章节：
   ```python
   "801xxx": [("section_name", "keyword", "keyword2", "guidance"), ...],
   ```

5. 生成规则：
   ```bash
   python scripts/generate_rules_from_real_reports.py --industry 801xxx
   ```

## 许可证

MIT
