#!/usr/bin/env python
"""金额类银行指标：从 GTA 面板取数、核锚、登记本体库（bank-indicator-money-unit-support）。

链路：windows-admin ``gta_panel``（只读角色 fdbiz_ro，值单位**元**）
      → ``docs/bank-money-indicator-sources.json``（指标 → 变量 + 口径钉死）
      → 观测行（``source_used='gta-panel'``，单位元）
      → 可选写入本体库 ``semantic_observations``

**为什么走面板而不是在报告正文里解析单位**：四种文本启发式（design.md 决策 1）
在 10 个样本上 3–5 个正确、3–4 个错成「元」，属过拟合。面板值统一以元存储。

纪律：
  · 面板滞后一财年（FY2025 全空）⇒ 该年记「源未入库」，**不插值、不拿上年顶替**；
  · 口径以口径表为准（存款/贷款均为资产负债表账面值，**含应计利息**）；
  · 核锚用 ``docs/golden-bank-money-gta.json``，证据取自年报原文，不是面板自证；
  · 写库靠 ``uq_sem_obs`` 幂等，重跑零重复行。

用法（需 psycopg2，用 fd-open-data-mcp 的 venv 跑）：
  ..venv/bin/python scripts/register_bank_money_from_gta.py --dump output/bank-money.json
  ..venv/bin/python scripts/register_bank_money_from_gta.py --dump output/bank-money.json --verify
  ..venv/bin/python scripts/register_bank_money_from_gta.py --dump output/bank-money.json --write
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

import bank_money_gta as bmg  # noqa: E402

DAAS_DB = _REPO.parent / "daas.db"


def _universe() -> list[str]:
    """银行宇宙 = 本机 daas.db 已入库报告的股票代码（与抽取/建锚同一批主体）。

    必须筛：面板是全上市公司口径，``利息净收入`` 一个年份有 200+ 家非银主体；
    把它们写进``financials.*``（银行指标概念）就是错的主体范围。
    """
    if not DAAS_DB.exists():
        raise SystemExit(f"缺 {DAAS_DB}；或用 --codes 显式给银行代码")
    conn = sqlite3.connect(str(DAAS_DB))
    try:
        return sorted(r[0] for r in conn.execute(
            "select distinct stock_code from report_documents").fetchall())
    finally:
        conn.close()


def _dsn(explicit: str | None) -> str:
    """GTA 面板连接串：显式 > GTA_PANEL_DSN > 由 FDBIZ_DOMAIN_PG_URL 换库名。

    business-mcp 的域名 DSN 指向 ``postgres`` 库，而 fdbiz_ro 在该库没有 CONNECT；
    它授权的库是 ``gta_panel``，所以这里把路径段换掉即可复用同一套凭据。
    """
    if explicit:
        return explicit
    if os.environ.get("GTA_PANEL_DSN"):
        return os.environ["GTA_PANEL_DSN"]
    base = os.environ.get("FDBIZ_DOMAIN_PG_URL")
    if not base:
        raise SystemExit("缺连接串：给 --dsn、GTA_PANEL_DSN 或 FDBIZ_DOMAIN_PG_URL")
    head = base.rsplit("/", 1)[0]
    return f"{head}/gta_panel"


def _fetch(dsn: str, cols: list[str], years: list[int], codes: list[str]) -> list[dict]:
    """读面板：一个变量的全部 bank-year 值（列名走白名单，来自口径表）。"""
    import psycopg2  # 延迟导入：不读库的路径（--verify 复核已有 dump）无需 psycopg2

    labels = {it["gta_name"]: it["indicator_zh"]
              for it in bmg.load_sources()["indicators"]}
    out: list[dict] = []
    with psycopg2.connect(dsn, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute("set statement_timeout = 60000")
            for col in cols:
                sql = (f"select id_org, year, {col} from panel "
                       f"where year = any(%s) and {col} is not null")
                params: list = [years]
                if codes:
                    sql += " and id_org = any(%s)"
                    params.append(codes)
                cur.execute(sql, params)
                for firm, year, val in cur.fetchall():
                    out.append({"indicator_zh": labels[col], "firm_id": firm,
                                "year": int(year), "value": float(val)})
    return out


def _write(sources: dict, rows: list[dict]) -> dict:
    """登记本体库。概念必须已在册（`docs/bank-money-concepts.json` 播种）。

    ``entity_id`` 是本体库的 ``entities.id``（代理键），**不是**六位代码：
    同一代码可同时存在 ``stock`` 与 ``company`` 两条（601398 就有 48/59 两行），
    所以按 ``entity_type='stock' and code=<代码>`` 解析，否则会写到错的主体上。
    ``value`` 在库里是 varchar，按整数串写，避免 1e13 量级走科学计数法。
    """
    import psycopg2

    dsn = os.environ.get("FD_OPEN_DATA_MCP_DATABASE_URL")
    if not dsn or not dsn.startswith("postgresql"):
        raise SystemExit("需要 FD_OPEN_DATA_MCP_DATABASE_URL 指向本体库（postgresql://）")
    ins = unresolved = 0
    with psycopg2.connect(dsn, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            for r in rows:
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
                if cur.rowcount:
                    ins += cur.rowcount
                else:
                    unresolved += 1
        conn.commit()
    return {"inserted": ins, "skipped_or_unresolved": unresolved, "attempted": len(rows)}


def _val_text(v: float) -> str:
    f = float(v)
    return str(int(f)) if f.is_integer() else repr(f)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn", help="GTA 面板连接串（默认由 FDBIZ_DOMAIN_PG_URL 换库名）")
    ap.add_argument("--years", default="2019-2024", help="年份区间，默认 2019-2024")
    ap.add_argument("--codes", help="股票代码逗号分隔；缺省用 daas.db 的银行宇宙")
    ap.add_argument("--dump", help="面板取值写到该 JSON（供 --verify 离线复核）")
    ap.add_argument("--from-dump", help="不连库，直接读该 JSON")
    ap.add_argument("--verify", action="store_true", help="用年报原文锚逐值核验")
    ap.add_argument("--write", action="store_true", help="写入本体库 semantic_observations")
    args = ap.parse_args()

    sources = bmg.load_sources()
    lo, _, hi = args.years.partition("-")
    years = list(range(int(lo), int(hi or lo) + 1))
    codes = [c.strip() for c in args.codes.split(",") if c.strip()] if args.codes else _universe()
    cols = bmg.variables(sources)

    if args.from_dump:
        payload = json.loads(Path(args.from_dump).read_text(encoding="utf-8"))
        values = payload["values"] if isinstance(payload, dict) else payload
    else:
        values = _fetch(_dsn(args.dsn), cols, years, codes)
    print(f"面板取值 {len(values)} 行（{len(cols)} 个变量 / {len(years)} 年）")

    rows, trace = bmg.to_observations(values, sources, years=years)
    print(f"观测行 {len(rows)}；留痕 empty={trace['empty']} unmapped={trace['unmapped']} "
          f"bad={len(trace['bad'])}")
    if trace["empty_years"]:
        gaps = ", ".join(f"{g['indicator_zh']}@{g['year']}" for g in trace["empty_years"])
        print(f"  整年无值（源未入库，不回填）: {gaps}")
    for ind, per_year in bmg.lag_note(sources, years, values).items():
        print(f"  {ind:12s} 非空家数 " + " ".join(f"{y}:{n}" for y, n in per_year.items()))

    if args.dump:
        p = Path(args.dump)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"values": values}, ensure_ascii=False), encoding="utf-8")
        print("dump →", p)

    rc = 0
    if args.verify:
        res = bmg.verify_anchors(values, bmg.load_golden())
        print(f"核锚 checked={res['checked']} mismatched={len(res['mismatched'])} "
              f"missing={len(res['missing'])}")
        for m in res["mismatched"]:
            print(f"  ✗ {m['indicator_zh']} {m['firm_id']} {m['year']} "
                  f"期望 {m['expected']} 得到 {m['got']}｜{m['evidence']}")
        for m in res["missing"]:
            print(f"  ? {m['indicator_zh']} {m['firm_id']} {m['year']} 面板无值｜{m['evidence']}")
        if res["mismatched"] or res["missing"]:
            rc = 1

    if args.write:
        print("写库:", _write(sources, rows))

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
