#!/usr/bin/env python
"""金额类银行指标：从 akshare 取数（主源）、与 GTA 交叉校验、登记本体库。

**主源为什么是 akshare**：同一批科目 GTA 与 akshare 都有，但 GTA 面板滞后一个财年
（FY2025 全空），akshare 没有时滞（实测工行到 2026-09-30 季报）。两源单位同为元、
口径同为资产负债表账面值（含应计利息），故重叠期应当逐值相等——不相等就是源缺陷。

口径纠正（本脚本落地的一条教训）：早期那份「逐值真值表」混了两种口径
（工行取含应计利息、招行取本金），不可作为唯一判据。本脚本一律以**年报附注的
加总关系**为锚：存款 = 本金 + 应计利息；贷款净额 = 总额 + 应计利息 − 减值准备。

用法（需 akshare + psycopg2，用 scraw-fd-open-data-mcp 的 venv）：
  ..venv/bin/python scripts/register_bank_money_from_akshare.py --years 2019-2025 --dump out.json --verify
  ..venv/bin/python scripts/register_bank_money_from_akshare.py --from-dump out.json --cross-check gta.json
  ..venv/bin/python scripts/register_bank_money_from_akshare.py --from-dump out.json --write
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import bank_money_akshare as BMA  # noqa: E402
import bank_money_gta as BMG  # noqa: E402

DAAS_DB = _REPO.parent / "daas.db"
SOURCE_USED = "akshare"


def _universe() -> list[str]:
    if not DAAS_DB.exists():
        raise SystemExit(f"缺 {DAAS_DB}；或用 --codes 显式给银行代码")
    conn = sqlite3.connect(str(DAAS_DB))
    try:
        return sorted(r[0] for r in conn.execute(
            "select distinct stock_code from report_documents").fetchall())
    finally:
        conn.close()


def _fetch(sources: dict, codes: list[str], years: list[int]) -> tuple[list[dict], list[dict]]:
    """逐只取资产负债表 + 利润表，抽出年报口径的四项金额指标。"""
    import akshare as ak

    rows: list[dict] = []
    trace: list[dict] = []
    for code in codes:
        sym = BMA.code_to_symbol(code)
        try:
            sheets = {
                "balance": ak.stock_balance_sheet_by_report_em(symbol=sym),
                "profit": ak.stock_profit_sheet_by_report_em(symbol=sym),
            }
        except Exception as exc:  # 单只失败不拖累整批，但要留痕
            trace.append({"firm_id": code, "reason": "fetch-failed", "detail": str(exc)[:160]})
            continue
        got, tr = BMA.periods_from_sheets(sheets, code, sources, years)
        rows.extend(got)
        if not got:
            trace.append({"firm_id": code, "reason": "no-annual-rows"})
        trace.extend({**t, "firm_id": code} for t in tr if t["reason"] == "statement-missing")
    return rows, trace


def _write(rows: list[dict]) -> dict:
    """写本体库。概念已在册（docs/bank-money-concepts.json 已播种）。"""
    import psycopg2

    dsn = os.environ.get("FD_OPEN_DATA_MCP_DATABASE_URL")
    if not dsn or not dsn.startswith("postgresql"):
        raise SystemExit("需要 FD_OPEN_DATA_MCP_DATABASE_URL 指向本体库（postgresql://）")
    src = BMG.load_sources()
    by_ind = {it["indicator_zh"]: it for it in src["indicators"]}
    obs, trace = BMG.to_observations(
        [{"indicator_zh": r["indicator_zh"], "firm_id": r["firm_id"], "year": r["year"],
          "value": r["value"]} for r in rows], src, source_used=SOURCE_USED)
    ins = skipped = 0
    with psycopg2.connect(dsn, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            for r in obs:
                cur.execute(
                    "insert into semantic_observations "
                    "(concept_id, entity_type, entity_id, date, granularity, value, unit, "
                    " source_used, fetched_at) "
                    "select c.id, %s, e.id, %s, %s, %s, %s, %s, now() "
                    "from concepts c, entities e "
                    "where c.code = %s and e.entity_type = %s and e.code = %s "
                    "on conflict do nothing",
                    (r["entity_type"], r["date"], r["granularity"],
                     _val_text(r["value"]), r["unit"], r["source_used"],
                     r["concept"], r["entity_type"], r["entity_code"]))
                ins += cur.rowcount or 0
                skipped += 0 if cur.rowcount else 1
        conn.commit()
    return {"inserted": ins, "skipped_or_unresolved": skipped, "attempted": len(obs),
            "concepts": len(by_ind)}


def _val_text(v: float) -> str:
    f = float(v)
    return str(int(f)) if f.is_integer() else repr(f)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", default="2019-2025")
    ap.add_argument("--codes", help="股票代码逗号分隔；缺省用 daas.db 的银行宇宙")
    ap.add_argument("--dump", help="取数结果写到该 JSON")
    ap.add_argument("--from-dump", help="不联网，直接读该 JSON")
    ap.add_argument("--verify", action="store_true", help="用年报原文锚核验")
    ap.add_argument("--cross-check", help="与该文件里的 GTA 取数结果逐值交叉校验")
    ap.add_argument("--write", action="store_true", help="写入本体库")
    args = ap.parse_args()

    sources = BMA.load_sources()
    lo, _, hi = args.years.partition("-")
    years = list(range(int(lo), int(hi or lo) + 1))
    codes = [c.strip() for c in args.codes.split(",") if c.strip()] if args.codes else _universe()

    if args.from_dump:
        payload = json.loads(Path(args.from_dump).read_text(encoding="utf-8"))
        rows = payload["values"] if isinstance(payload, dict) else payload
        trace = payload.get("trace", []) if isinstance(payload, dict) else []
    else:
        print(f"取数：{len(codes)} 只银行 × {len(years)} 年（akshare 逐只调用，耗时较长）")
        rows, trace = _fetch(sources, codes, years)

    print(f"取得 {len(rows)} 行；留痕 {len(trace)} 条")
    for t in trace[:6]:
        print("  !", t)
    by_year: dict[int, int] = {}
    for r in rows:
        by_year[r["year"]] = by_year.get(r["year"], 0) + 1
    print("  年份分布 " + " ".join(f"{y}:{n}" for y, n in sorted(by_year.items())))

    rc = 0
    if args.dump:
        p = Path(args.dump)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"values": rows, "trace": trace}, ensure_ascii=False),
                     encoding="utf-8")
        print("dump →", p)

    if args.verify:
        res = BMG.verify_anchors(rows, BMG.load_golden(), sources)
        print(f"核锚 checked={res['checked']} mismatched={len(res['mismatched'])} "
              f"missing={len(res['missing'])}")
        for m in res["mismatched"]:
            print(f"  ✗ {m['indicator_zh']} {m['firm_id']} {m['year']} "
                  f"期望 {m['expected']} 得到 {m['got']}")
        for m in res["missing"]:
            print(f"  ? {m['indicator_zh']} {m['firm_id']} {m['year']} 无值｜{m['evidence']}")
        if res["mismatched"] or res["missing"]:
            rc = 1

    if args.cross_check:
        gta = json.loads(Path(args.cross_check).read_text(encoding="utf-8"))
        gta_vals = gta["values"] if isinstance(gta, dict) else gta
        cc = BMA.cross_check(rows, gta_vals)
        print(f"交叉校验 compared={cc['compared']} mismatched={len(cc['mismatched'])} "
              f"only_akshare={len(cc['only_akshare'])} only_gta={len(cc['only_gta'])}")
        for m in cc["mismatched"][:10]:
            print(f"  ✗ {m['indicator_zh']} {m['firm_id']} {m['year']} "
                  f"akshare={m['akshare']} gta={m['gta']}")
        if cc["mismatched"]:
            rc = 1

    if args.write:
        print("写库:", _write(rows))

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
