#!/usr/bin/env python3
"""tool-surface.json 生成器：从运行时工具面导出上牌 manifest（fd-cn-report 版）。

**为什么用生成器而不是手写 manifest**：手写的清单会与代码漂移——加了工具忘了
登记，或登记了已删除的工具。`mcp-surface-contract` 要求 manifest 随代码同步维护，
把"同步"落成一条命令（而不是一句纪律）是唯一可靠的做法。

事实源取 `server.app`（FastMCP 实例，即 server 实际注册的全部 44 工具）的
`_list_tools()`——工具名 / 行为属性 / 输出结构全部从运行时派生，故新增/删除
工具后重跑本脚本即可，manifest 不会漂。分组归属是本仓唯二的静态声明之一
（另一处是 `TOOL_ANNOTATIONS`），新工具若未入组，本脚本直接报错退出——
静默漏登是不允许的。

行为属性（readOnlyHint 等）真源在 `server.TOOL_ANNOTATIONS`，随 @app.tool 注册
进运行时；本脚本只做搬运，不做第二份声明。

用法：
    uv run python scripts/gen_surface.py            # 写 tool-surface.json
    uv run python scripts/gen_surface.py --check    # 只比对，不写（CI / selfcheck 用）
退出码：0 一致或已写入 / 1 --check 下发现漂移 / 2 工具未入组等结构错误。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "tool-surface.json"

SERVER_NAME = "fd-cn-report"
ENTRY_PATH = "/fd-cn-report"
PRODUCT_LINE = "securities"
MCP_ENDPOINT = "http://cheap6.mesh.finddata.cn:31852/mcp"

#: 分组归属（静态声明）：组名 →（组说明, 成员工具名）。顺序即 manifest 顺序。
#: 工具名必须与 server.py 的注册名逐一对应；新工具未入组 → build 时报错。
GROUPS: dict[str, tuple[str, list[str]]] = {
    "outline_extraction": (
        "研报目录与分节抽取：list_outline 拉取年报/招股书等公告 PDF/HTML 并解析目录树，"
        "extract_section 按标题/正则/序号抽取单节正文。取回的原文落本地报告缓存、"
        "provenance（report_id/section 元数据）upsert 进本地 SQLite——均为透明记忆化，"
        "不改变任何面向用户的数据。",
        ["list_outline", "extract_section"],
    ),
    "ai_extraction": (
        "LLM 结构化抽取：ai_extract 对分节文本按调用方给的 JSON Schema 抽记录数组"
        "（调外部 LLM，openWorld；无本地落库）。缓存与落库均由上层组合工具负责。",
        ["ai_extract"],
    ),
    "es_store": (
        "ES 检索库存取（**本组非纯读**）：search_reports 全文+过滤检索（只读）；"
        "index_records 把抽取记录 bulk 落 cnreport-{year} 索引（写，幂等键 "
        "report_id+section_id）；delete_index 删整年索引及其元数据行（**destructive**，"
        "需 confirm=true）。ES 是本服务自己的库，openWorld=false。",
        ["index_records", "search_reports", "delete_index"],
    ),
    "company_api": (
        "A 股公司画像与公告（巨潮 CNINFO 线）：公司解析 / 公告列表 / 单公告 / "
        "三大报表结构化 / 便捷分节抽取 / 披露类别目录 / 特殊报告（招股、增发、业绩预告等）。"
        "便捷工具的 PDF 下载落报告缓存（透明记忆化）。",
        ["get_company", "list_filings", "get_filing", "get_financials", "get_section",
         "list_report_types", "get_special_report", "get_financial_statements"],
    ),
    "cache_mgmt": (
        "报告缓存管理（**本组非纯读**）：list_cache 列缓存清单（只读）；"
        "clear_cache 逐出缓存文件（**destructive**，可全清）。缓存在 pod 本地磁盘，"
        "清掉只影响后续取数速度，不丢任何库内数据。",
        ["list_cache", "clear_cache"],
    ),
    "indicator_rules": (
        "银行业指标规则引擎：规则浏览（indicator_rules.json 驱动）、单指标解析"
        "（akshare/报告节/本地计算三路路由）、整包抽取（一次取 PDF + 分节批式 LLM + "
        "Python 抽取器 + 本地比率），bundle 落盘缓存供免费重跑（透明记忆化）。",
        ["list_indicators", "get_indicator", "extract_indicators",
         "extract_indicators_by_position"],
    ),
    "hk_stock": (
        "港股画像/公告/报表/分节（HK 线）：与 company_api 同构的港股四件套。",
        ["get_hk_company", "list_hk_filings", "get_hk_financials", "get_hk_section"],
    ),
    "sse_official": (
        "上交所官方线（sse.com.cn / 上证 e 互动）：公司解析 / 披露列表 / 年报分节 / "
        "投资者互动问答。",
        ["get_sse_company", "list_sse_filings", "get_sse_section", "get_sse_interaction"],
    ),
    "szse_official": (
        "深交所官方线（szse.cn / 互动易）：公司解析 / 披露列表 / 年报分节 / 投资者互动问答。",
        ["get_szse_company", "list_szse_filings", "get_szse_section", "get_szse_interaction"],
    ),
    "bse_official": (
        "北交所官方线（bse.cn，巨潮兜底）：公司解析 / 披露列表 / 年报分节，行内带 "
        "source: bse|cninfo。",
        ["get_bse_company", "list_bse_filings", "get_bse_section"],
    ),
    "csrc_official": (
        "证监会官方线（csrc.gov.cn）：监管公告列表 / IPO 首发审核状态 / 并购重组审核状态 / "
        "行政处罚与执法动态。",
        ["list_csrc_filings", "get_csrc_ipo_review", "get_csrc_merger_review",
         "list_csrc_enforcement"],
    ),
    "ministry_stats": (
        "部委统计：来源目录（本地静态） / 部委统计页 HTML 表解析（mof/pboc/safe/gacc/nfra） / "
        "国家统计局指标查询。",
        ["list_ministries", "get_ministry_stat", "get_nbs_stat"],
    ),
    "rule_audit": (
        "规则库治理面（**本组非纯读**，运维性质）：audit_rule_gaps 扫描 out/ 抽取包并"
        "**写**审计 JSON 产物；open_industry_rules_dashboard 在 pod 本地**起**一个"
        "dashboard HTTP 服务（有副作用，不可幂等）。两工具面向本仓维护者，调用方少用。",
        ["audit_rule_gaps", "open_industry_rules_dashboard"],
    ),
}

DESCRIPTION_TEMPLATE = (
    "fd-cn-report 中国金融研报 MCP 能力面，**十三组**共 {count} 工具：①研报目录/分节抽取与 "
    "LLM 结构化抽取；②ES 检索库存取（index_records 写 / delete_index 删）；③A 股（巨潮）、"
    "港股、上交所、深交所、北交所、证监会六条官方/半官方数据线；④银行业指标规则引擎；"
    "⑤部委统计；⑥规则库治理（审计产物写 / dashboard 起服）。"
    "读写面**如实标注**（MCP annotations）：39 只读 + 5 写面"
    "（index_records 落库 / delete_index 删索引 / clear_cache 清缓存 / audit_rule_gaps 写审计产物 / "
    "open_industry_rules_dashboard 起 HTTP 服务）。"
    "取数类工具的磁盘缓存与 provenance upsert 属透明记忆化，不改变面向用户的数据；"
    "外网取数与 LLM 调用类工具 openWorldHint=true。共享实例、无逐用户状态。"
)

#: 共享实例（k8s cheap/fd-prod NodePort 31852；无逐用户状态）
HOSTING = ["shared-instance"]

CONSUMPTION_NOTE = (
    "共享实例：查询/抽取面无逐用户状态（报告缓存与 bundle 缓存为透明记忆化，跨调用者共享"
    "不泄露——缓存键即公告 URL/公司+年份）；ES 库为本服务自有数据面。写面五工具"
    "（index_records/delete_index/clear_cache/audit_rule_gaps/open_industry_rules_dashboard）"
    "面向数据管道维护场景，消费侧 pack 不应引用。"
)

#: 尚无 pack 技能引用本服务。空表是诚实值：一旦有技能进 pack，在此登记并由
#: selfcheck 反向校验。
SKILLS_ELIGIBLE: list[str] = []


def _runtime_tools() -> list:
    sys.path.insert(0, str(REPO))
    from server import app

    return asyncio.run(app._list_tools())


def build_manifest() -> dict:
    tools = _runtime_tools()
    runtime_names = {t.name for t in tools}

    grouped: set[str] = set()
    for members in GROUPS.values():
        grouped.update(members[1])
    unassigned = sorted(runtime_names - grouped)
    phantom = sorted(grouped - runtime_names)
    if unassigned or phantom:
        print(f"✗ 分组归属与运行时不一致：未入组={unassigned} 幽灵条目={phantom}",
              file=sys.stderr)
        raise SystemExit(2)

    groups = []
    for gname, (gdesc, members) in GROUPS.items():
        groups.append({
            "group": gname,
            "level": "commercial",
            "tools": sorted(members),
            "description": gdesc,
        })

    annotations = {}
    output_capable = []
    for t in tools:
        a = t.annotations
        annotations[t.name] = {} if a is None else {
            "readOnlyHint": a.readOnlyHint,
            "destructiveHint": a.destructiveHint,
            "idempotentHint": a.idempotentHint,
            "openWorldHint": a.openWorldHint,
        }
        if getattr(t, "output_schema", None):
            output_capable.append(t.name)

    total = len(tools)
    return {
        "schema": "mcp-tool-surface/v1",
        "server": SERVER_NAME,
        "entry_path": ENTRY_PATH,
        "product_line": PRODUCT_LINE,
        "hosting": HOSTING,
        # 工具数从运行时派生：写死在描述里必然随组增长而漂，而描述也是清单的一部分。
        "description": DESCRIPTION_TEMPLATE.format(count=total),
        "skills_eligible_for_packs": SKILLS_ELIGIBLE,
        # 行为属性从运行时派生（mcp-tool-annotations，真源 server.TOOL_ANNOTATIONS）：
        # 清单里再手抄一份就等于给协议层属性造了第二个事实源，两边必然漂。
        "tool_annotations": annotations,
        # 输出结构从运行时派生（mcp-result-contract）：`undeclared` 显式列出无
        # output_schema 的工具，使"没有声明"这件事在清单里可见，而不是静默空缺。
        "output_structure": {
            "declared": sorted(output_capable),
            "undeclared": sorted(runtime_names - set(output_capable)),
            "source": "运行时实测（fastmcp structured output；v1 未建独立 outputs.json 生成器）",
            "note": "declared = fastmcp 按返回标注生成的 output_schema 工具集；"
                    "required/类型语义以运行时 schema 为准。",
        },
        "naming_convention": {
            "order": "verb_noun",
            "applies_to": "new_tools",
            "note": ("新工具一律 `动词_名词`。既有工具名即此形态（list_/get_/extract_/"
                     "search_/index_/delete_/clear_/audit_/open_）；不改名——改名会破坏"
                     "已发布 pack 的引用。"),
            "historical": "none",
            "prefix_policy": ("跨服务同名工具不得靠前缀区分（前缀是服务标识而非工具语义）；"
                              "同名消解靠描述里写明部署与数据源差异。"),
        },
        "tool_groups": groups,
        "registry": {
            "entry_path": ENTRY_PATH,
            "expected_tool_count": total,
            "consumption_note": CONSUMPTION_NOTE,
            "mcp_endpoint": MCP_ENDPOINT,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="只比对现有 manifest，不写入（发现漂移退出码 1）")
    args = ap.parse_args()

    fresh = build_manifest()
    text = json.dumps(fresh, ensure_ascii=False, indent=2) + "\n"

    if args.check:
        if not MANIFEST.exists():
            print(f"✗ manifest 缺失：{MANIFEST}", file=sys.stderr)
            return 1
        cur = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if cur != fresh:
            cur_tools = {t for g in cur.get("tool_groups", []) for t in g.get("tools", [])}
            fresh_tools = {t for g in fresh["tool_groups"] for t in g["tools"]}
            added = sorted(fresh_tools - cur_tools)
            removed = sorted(cur_tools - fresh_tools)
            print("✗ manifest 与运行时工具面漂移：", file=sys.stderr)
            if added:
                print(f"  运行时有而 manifest 无（需登记）：{added}", file=sys.stderr)
            if removed:
                print(f"  manifest 有而运行时无（需删除）：{removed}", file=sys.stderr)
            if not added and not removed:
                print("  工具集相同但其它字段有差异（description / 分组 / 计数 / 注解）",
                      file=sys.stderr)
            return 1
        print(f"✓ manifest 与运行时一致（{fresh['registry']['expected_tool_count']} 工具）")
        return 0

    MANIFEST.write_text(text, encoding="utf-8")
    print(f"✓ 已写入 {MANIFEST.relative_to(REPO.parent)}")
    for g in fresh["tool_groups"]:
        print(f"    {g['group']:24s} {len(g['tools']):2d} 工具  [{g['level']}]")
    ro = sum(1 for a in fresh["tool_annotations"].values() if a.get("readOnlyHint"))
    print(f"  合计 {fresh['registry']['expected_tool_count']} 工具（只读 {ro} / 写面 {fresh['registry']['expected_tool_count'] - ro}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
