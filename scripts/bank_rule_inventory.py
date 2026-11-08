#!/usr/bin/env python
"""银行 scoped 规则「在册≠可用」盘点（harden-bank-indicator-rules 1.2/1.3/6.2）。

把 13 个 bank-scoped 指标的**每一行**摊开，逐行判定可用性，并回答一个关键问题：
`resolve_rule()` 实际选中的是哪一行——因为引擎**每个指标只取一行**，只修别的行等于白修。

判定口径（spec「规则可用性 SHALL 以四项判据共同成立为准」）：
  · **空壳**   —— `source` 为空 / 字面 `null` / 解析后既无 selectors 也无明确口径
  · **双层**   —— `applies_to` 是「JSON 套 JSON」，读取面解一层得字符串 → 静默不适用
  · **非报告口径** —— `source` 是 `formula` 或 `statement`+`field`（走 akshare/派生，不走报告 PDF）
  · **可修**   —— `source` 有 selectors，但 applies_to 仍双层（休眠）
  · **可用**   —— 四列均为单层 + selectors + 该指标在 golden 锚里存在

用法：
  python3 scripts/bank_rule_inventory.py                     # 打印表格
  python3 scripts/bank_rule_inventory.py --out reports/banking-report-ingest/rule-inventory-2026-11-08.md
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
DAAS_DB = _REPO.parent / "daas.db"
GOLDEN = _REPO / "docs" / "golden-bank-indicators.json"

import bank_money_gta as BMG  # noqa: E402

BANK13 = ['不良率', '净利息收入', '发放贷款及垫款', '客户存款', '手续费及佣金净收入',
          '拨贷比_coverage', '流动性比例（人民币）', '质押贷款净增加额', '贷款和垫款总额',
          '逾期90天重组贷款率', '逾期贷款率', '重组贷款率', '风险加权资产合计']
JSON_COLS = ("applies_to", "source", "aliases", "value_range")


def _decode(raw):
    """(值, 层数)。层数 2 = 双层编码，1 = 正常，0 = 空/null。"""
    if raw is None or raw == "":
        return None, 0
    try:
        once = json.loads(raw)
    except (TypeError, ValueError):
        return raw, 1
    if isinstance(once, str):
        try:
            return json.loads(once), 2
        except (TypeError, ValueError):
            return once, 1
    if once is None:
        return None, 0
    return once, 1


def _source_form(inner) -> str:
    if inner is None:
        return "空壳"
    if not isinstance(inner, dict):
        return "空壳"
    if inner.get("selectors"):
        return "selectors"
    if inner.get("formula"):
        return "formula"
    if inner.get("statement") or inner.get("field"):
        return "statement"
    return "空壳"


def _applies_form(inner, depth: int) -> str:
    if depth == 0 or inner is None:
        return "null(全行业)"
    if isinstance(inner, dict):
        tag = "双层" if depth == 2 else "单层"
        return f"{tag}:{inner.get('industry') or '*'}"
    return "字面str"


def collect() -> list[dict]:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    anchored = set(golden["indicators"])
    # resolve_rule() 按 `order_by(taxonomy_code, indicator)` 取**第一个**同名行，
    # 且返回的 dict 不带 id。这里用同样的排序在 SQL 里复现"选中行"，否则盘点表里
    # 「选中」列永远空着——而只修没被选中的行等于白修。
    conn0 = sqlite3.connect(str(DAAS_DB))
    resolved: dict[str, int | None] = {}
    for ind in BANK13:
        row = conn0.execute(
            "SELECT id FROM llm_rules WHERE indicator = ? "
            "ORDER BY taxonomy_code, indicator, id LIMIT 1", (ind,)).fetchone()
        resolved[ind] = row[0] if row else None
    conn0.close()

    conn = sqlite3.connect(str(DAAS_DB))
    conn.row_factory = sqlite3.Row
    marks = ",".join("?" * len(BANK13))
    rows = conn.execute(
        f"SELECT id, indicator, {', '.join(JSON_COLS)} FROM llm_rules "
        f"WHERE indicator IN ({marks}) ORDER BY indicator, id", BANK13).fetchall()
    conn.close()

    out = []
    for row in rows:
        src_inner, src_depth = _decode(row["source"])
        ap_inner, ap_depth = _decode(row["applies_to"])
        sform = _source_form(src_inner)
        aform = _applies_form(ap_inner, ap_depth)
        selected = resolved.get(row["indicator"]) == row["id"]
        if sform == "空壳":
            verdict = "空壳（点名即崩）"
        elif sform in ("formula", "statement"):
            verdict = "非报告口径"
        elif ap_depth == 2:
            verdict = "可修（休眠：applies_to 双层）"
        elif row["indicator"] in anchored:
            verdict = "可用"
        else:
            verdict = "待建锚"
        # 金额类已被结构化源接管/判不可得 —— 盖掉上面「可修」式的旧判词，
        # 否则读的人会去修报告选择器（已四次证伪的路）。
        verdict = BMG.inventory_verdict(row["indicator"], verdict)
        out.append({"id": row["id"], "indicator": row["indicator"],
                    "source": sform, "applies_to": aform, "selected": selected,
                    "verdict": verdict})
    return out


def _verdict_kind(verdict: str) -> str:
    """判定归并成类别，避免长判词把「判定分布」打散成十几条。"""
    for kind in ("已覆盖", "无源覆盖", "空壳", "可用", "待建锚", "非报告口径", "可修"):
        if verdict.startswith(kind):
            return kind
    return verdict


def render(rows: list[dict]) -> str:
    lines = ["| id | 指标 | source | applies_to | resolve_rule 选中 | 判定 |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r['indicator']} | {r['source']} | {r['applies_to']} | "
                     f"{'✓' if r['selected'] else ''} | {r['verdict']} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="写到 markdown 文件")
    args = ap.parse_args()

    rows = collect()
    table = render(rows)
    print(table)
    by_verdict: dict[str, int] = {}
    for r in rows:
        kind = _verdict_kind(r["verdict"])
        by_verdict[kind] = by_verdict.get(kind, 0) + 1
    print("\n判定分布:", by_verdict)
    miss_sel = [r["indicator"] for r in rows if r["selected"] is None]
    if miss_sel:
        print("警告：这些指标 resolve_rule 没返回行:", sorted(set(miss_sel)))

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "# 银行 scoped 规则盘点：在册 ≠ 可用\n\n"
            f"- 生成：2026-11-08（`scripts/bank_rule_inventory.py`）\n"
            f"- 范围：13 个 bank-scoped 指标的全部 {len(rows)} 行\n"
            "- 关键：`resolve_rule()` **每个指标只返回一行**，表中「选中」列才是真正生效的那一行\n\n"
            + table + "\n\n判定分布：" + json.dumps(by_verdict, ensure_ascii=False) + "\n",
            encoding="utf-8")
        print("written", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
