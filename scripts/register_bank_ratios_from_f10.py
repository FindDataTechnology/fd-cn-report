#!/usr/bin/env python
"""银行监管比率：从东财 F10 取数、核锚、登记本体库（阈值告警的数据基础）。

**要解决的问题**：阈值告警原先只覆盖 5/42 家——比率只来自报告抽取（5 家试点）。
东财 F10 主要指标直接带 4 个监管比率，覆盖全部 A 股银行、无滞后。

字段口径不是猜的：harden 期从报告原文逐值核过的 golden 锚（5 家 × 4 项 = 20 点）
与 FY2025 F10 值 **20/20 完全一致**；`LIQUIDATION_RATIO` 因与 golden 流动性比例
（108.03 vs 63.20）不符而被明确排除，见 `bank_ratio_f10.REJECTED`。

用法：
  ..venv/bin/python scripts/register_bank_ratios_from_f10.py --years 2024-2025 --dump out.json --verify
  ..venv/bin/python scripts/register_bank_ratios_from_f10.py --from-dump out.json --write
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

import bank_ratio_f10 as F10  # noqa: E402

DAAS_DB = _REPO.parent / "daas.db"
GOLDEN = _REPO / "docs" / "golden-bank-indicators.json"


def _universe() -> list[str]:
    if not DAAS_DB.exists():
        raise SystemExit(f"缺 {DAAS_DB}；或用 --codes 显式给银行代码")
    conn = sqlite3.connect(str(DAAS_DB))
    try:
        return sorted(r[0] for r in conn.execute(
            "select distinct stock_code from report_documents").fetchall())
    finally:
        conn.close()


def _fetch(codes: list[str], years: list[int]) -> tuple[list[dict], list[dict]]:
    values: list[dict] = []
    trace: list[dict] = []
    for code in codes:
        try:
            rows = F10.fetch_rows(code)
        except Exception as exc:  # noqa: BLE001 — 单只失败不拖累整批
            trace.append({"firm_id": code, "reason": "fetch-failed", "detail": str(exc)[:160]})
            continue
        got, tr = F10.to_values(rows, code, years)
        values.extend(got)
        trace.extend(tr)
        if not got:
            trace.append({"firm_id": code, "reason": "no-annual-rows"})
    return values, trace


def _write(values: list[dict]) -> dict:
    """写本体库。指标名与概念码由 `F10.FIELDS` 决定，不在代码里硬编码概念名。"""
    import psycopg2

    dsn = os.environ.get("FD_OPEN_DATA_MCP_DATABASE_URL")
    if not dsn or not dsn.startswith("postgresql"):
        raise SystemExit("需要 FD_OPEN_DATA_MCP_DATABASE_URL 指向本体库")
    ins = skipped = 0
    with psycopg2.connect(dsn, connect_timeout=10) as conn, conn.cursor() as cur:
        # 先取已有 (概念, 主体, 日期)：**同一「概念+主体+日期」只留一个源**。
        # 5 家试点在 2025-12-31 已有 cn-report 的值（golden 逐值核过），
        # 这里不覆盖、也不并排放第二行——单源供数的纪律与金额指标一致。
        concepts = sorted({c for _col, c, _u in F10.FIELDS.values()})
        cur.execute(
            "select c.code, e.code, o.date from semantic_observations o "
            "join concepts c on c.id = o.concept_id "
            "join entities e on e.id = o.entity_id "
            "where e.entity_type = 'stock' and c.code = any(%s)", (concepts,))
        existing = {(c, e, d) for c, e, d in cur.fetchall()}
        for v in values:
            _col, concept, unit = F10.FIELDS[v["indicator_zh"]]
            if (concept, v["firm_id"], f"{v['year']}-12-31") in existing:
                skipped += 1
                continue
            cur.execute(
                "insert into semantic_observations "
                "(concept_id, entity_type, entity_id, date, granularity, value, unit, "
                " source_used, fetched_at) "
                "select c.id, 'stock', e.id, %s, 'year', %s, %s, %s, now() "
                "from concepts c, entities e "
                "where c.code = %s and e.entity_type = 'stock' and e.code = %s "
                "on conflict do nothing",
                (f"{v['year']}-12-31", _num(v["value"]), unit, F10.SOURCE_USED,
                 concept, v["firm_id"]))
            ins += cur.rowcount or 0
            skipped += 0 if cur.rowcount else 1
        conn.commit()
    return {"inserted": ins, "skipped_existing_or_unresolved": skipped,
            "attempted": len(values)}


def _num(x: float) -> str:
    f = float(x)
    return str(int(f)) if f.is_integer() else repr(f)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", default="2024-2025")
    ap.add_argument("--codes", help="股票代码逗号分隔；缺省用 daas.db 的银行宇宙")
    ap.add_argument("--dump")
    ap.add_argument("--from-dump")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)

    lo, _, hi = args.years.partition("-")
    years = list(range(int(lo), int(hi or lo) + 1))
    codes = [c.strip() for c in args.codes.split(",") if c.strip()] if args.codes else _universe()

    if args.from_dump:
        payload = json.loads(Path(args.from_dump).read_text(encoding="utf-8"))
        values, trace = payload["values"], payload.get("trace", [])
    else:
        print(f"取数：{len(codes)} 只银行（东财 F10，逐只调用）")
        values, trace = _fetch(codes, years)

    by_ind: dict[str, int] = {}
    for v in values:
        by_ind[v["indicator_zh"]] = by_ind.get(v["indicator_zh"], 0) + 1
    print(f"取得 {len(values)} 行；留痕 {len(trace)} 条")
    print("  指标分布:", by_ind)
    firms = {v["firm_id"] for v in values}
    print(f"  覆盖主体: {len(firms)} 家")

    rc = 0
    if args.dump:
        p = Path(args.dump)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"values": values, "trace": trace}, ensure_ascii=False),
                     encoding="utf-8")
        print("dump →", p)

    if args.verify:
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        res = F10.verify_golden(values, golden)
        print(f"核锚 checked={res['checked']} mismatched={len(res['mismatched'])} "
              f"missing={len(res['missing'])}")
        for m in res["mismatched"][:10]:
            print(f"  ✗ {m['indicator_zh']} {m['firm_id']} {m['year']} "
                  f"期望 {m['expected']} 得到 {m['got']}")
        for m in res["missing"][:10]:
            print(f"  ? {m['indicator_zh']} {m['firm_id']} {m['year']} 无值")
        if res["mismatched"] or res["missing"]:
            rc = 1

    if args.write:
        print("写库:", _write(values))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
