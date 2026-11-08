#!/usr/bin/env python
"""银行监控白名单生成器（awaken-banking-report-ingest 2.1）。

监控范围 = 东财银行板块 BK0475 实时成分（A 股上市银行，2026-11-08 实取 42 家）。
orgId 一律取自巨潮官方映射表（`/new/data/szse_stock.json`，覆盖全部 A 股 6263 行），
**不按交易所前缀拼接**；纯 H 股银行（`hke_stock.json`）只计数不入清单。

⚠️ orgId 前缀不可用于推断交易所：官方映射里同一交易所混用三种前缀——
   601398 工商银行 → `jjxt0000019`（沪）
   600036 招商银行 → `gssh0600036`（沪）
   002142 宁波银行 → `9900003281`（深）
   601166 兴业银行 → `9900002081`（沪）
故交易所按 **代码段**判定（6→sse，0/3→szse，4/8→bse），orgId 原样保留。

输出（机器可读，供 ingest 管道与看板消费）：
  output/bank-whitelist/latest.json            恒指最新快照
  output/bank-whitelist/whitelist-<YYYYMMDD>.json  当次快照
  output/bank-whitelist/codes.txt              代码清单（每行一个）

JSON 形状：
{
  "generated_at": ISO,
  "scope": {"board": "BK0475", "count": 42, "h_share_excluded": N},
  "whitelist": [ {code, name, org_id, exchange, org_prefix}, ... ],
  "count_total": N,
  "cross_check": {"securities_whitelist": {...}}   # --check 时填
}

用法（fd-cn-report venv 或系统 python3 均可，仅需标准库）：
  python3 scripts/bank_whitelist.py            # 生成并落盘
  python3 scripts/bank_whitelist.py --check    # 重取一遍与 latest.json 对账（幂等验证）
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

_THIS = Path(__file__).resolve()
_REPO = _THIS.parent.parent
OUT_DIR = _REPO / "output" / "bank-whitelist"

#: 证券业白名单（fd-industry-data 产出），--check 时做交集核对
SECURITIES_LATEST = _REPO.parent / "fd-industry-data" / "output" / "securities-whitelist" / "latest.json"

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
_CNINFO = "http://www.cninfo.com.cn"
_EM_BOARD = "https://push2.eastmoney.com/api/qt/clist/get"
_EM_PARAMS = {
    "pn": "1", "pz": "200", "po": "1", "np": "1", "fltt": "2", "invt": "2",
    "fid": "f3", "fs": "b:BK0475", "fields": "f12,f14,f13",
    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
}


def _get_json(url: str, params: dict | None = None) -> object:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_board() -> list[dict]:
    """BK0475 成分 → [{code, name}]（东财实时）。"""
    payload = _get_json(_EM_BOARD, _EM_PARAMS)
    data = payload.get("data") or {}
    rows = data.get("diff") or []
    if not rows:
        raise RuntimeError("BK0475 returned no constituents — 板块号失效或东财接口变更")
    out = []
    for row in rows:
        code = str(row.get("f12") or "").zfill(6)
        name = str(row.get("f14") or "").strip()
        if code and name:
            out.append({"code": code, "name": name})
    if data.get("total") and int(data["total"]) != len(out):
        print(f"[warn] BK0475 total={data['total']} 但只解析到 {len(out)} 行", file=sys.stderr)
    return sorted(out, key=lambda r: r["code"])


def fetch_official_org_ids() -> dict[str, dict]:
    """巨潮官方映射：A 股 code → {org_id, name, category}。"""
    payload = _get_json(f"{_CNINFO}/new/data/szse_stock.json")
    rows = (payload or {}).get("stockList") or []
    if not rows:
        raise RuntimeError("szse_stock.json 无数据 — 官方映射表不可用，拒绝拼接 orgId")
    return {str(r["code"]).zfill(6): r for r in rows if r.get("code")}


def fetch_h_share_count() -> int:
    """纯 H 股银行计数（仅用于「二期另立」的排除声明，不入清单）。"""
    try:
        payload = _get_json(f"{_CNINFO}/new/data/hke_stock.json")
    except Exception as exc:  # 计数失败不阻塞主清单
        print(f"[warn] hke_stock.json 拉取失败，H 股计数置 0：{exc}", file=sys.stderr)
        return 0
    rows = (payload or {}).get("stockList") or []
    return sum(1 for r in rows if "银行" in str(r.get("zwjc") or ""))


def exchange_of(code: str) -> str:
    """按代码段判交易所（orgId 前缀混用，不可依赖）。"""
    if code.startswith("6"):
        return "sse"
    if code.startswith(("0", "3")):
        return "szse"
    if code.startswith(("4", "8")):
        return "bse"
    return ""


def build_whitelist() -> dict:
    board = fetch_board()
    official = fetch_official_org_ids()
    entries: list[dict] = []
    unmapped: list[str] = []
    for row in board:
        code = row["code"]
        hit = official.get(code)
        if not hit:
            unmapped.append(code)
            continue
        org_id = str(hit.get("orgId") or "")
        entries.append({
            "code": code,
            "name": row["name"],
            # 名称以官方映射为准更稳（东财简称偶有无后缀差异），但板块名是监控口径，
            # 二者不一致时两个都留，便于对账。
            "name_official": str(hit.get("zwjc") or ""),
            "org_id": org_id,
            "exchange": exchange_of(code),
            "org_prefix": org_id[:4],
        })
    doc = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": {
            "board": "BK0475",
            "board_name": "银行",
            "count": len(entries),
            "h_share_excluded": fetch_h_share_count(),
            "h_share_note": "纯 H 股银行不在本范围（二期另立）",
            "unmapped": unmapped,
        },
        "whitelist": entries,
        "count_total": len(entries),
    }
    return doc


def write_outputs(doc: dict) -> list[Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    snapshot = OUT_DIR / f"whitelist-{stamp}.json"
    latest = OUT_DIR / "latest.json"
    codes = OUT_DIR / "codes.txt"
    for path in (snapshot, latest):
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    codes.write_text("\n".join(e["code"] for e in doc["whitelist"]) + "\n", encoding="utf-8")
    return [snapshot, latest, codes]


def cross_check_securities(new: dict) -> dict:
    """与证券业白名单交集核对：重叠实体代码归属必须一致（orgId 相同）。"""
    if not SECURITIES_LATEST.exists():
        return {"available": False, "note": f"未找到 {SECURITIES_LATEST}"}
    sec = json.loads(SECURITIES_LATEST.read_text(encoding="utf-8"))
    sec_codes = {e["code"]: e for e in sec.get("whitelist", [])}
    overlap = sorted(set(sec_codes) & {e["code"] for e in new["whitelist"]})
    problems = [
        {"code": c, "securities_name": sec_codes[c]["name"],
         "bank_name": next(e["name"] for e in new["whitelist"] if e["code"] == c)}
        for c in overlap
        if sec_codes[c]["name"] != next(e["name"] for e in new["whitelist"] if e["code"] == c)
    ]
    return {
        "available": True,
        "securities_count": sec.get("count_total"),
        "overlap_count": len(overlap),
        "overlap_codes": overlap,
        "name_mismatch": problems,
    }


def check_against_latest() -> int:
    latest = OUT_DIR / "latest.json"
    if not latest.exists():
        print("no latest.json — run without --check first", file=sys.stderr)
        return 2
    old = json.loads(latest.read_text(encoding="utf-8"))
    new = build_whitelist()
    problems: list[str] = []
    old_codes = {e["code"]: e for e in old["whitelist"]}
    new_codes = {e["code"]: e for e in new["whitelist"]}
    gone, added = sorted(set(old_codes) - set(new_codes)), sorted(set(new_codes) - set(old_codes))
    if gone or added:
        problems.append(f"成分漂移 removed={gone} added={added}")
    for code in sorted(set(old_codes) & set(new_codes)):
        if old_codes[code]["org_id"] != new_codes[code]["org_id"]:
            problems.append(
                f"{code} orgId 漂移 {old_codes[code]['org_id']} -> {new_codes[code]['org_id']}")
        if old_codes[code]["name"] != new_codes[code]["name"]:
            problems.append(
                f"{code} 简称漂移 {old_codes[code]['name']} -> {new_codes[code]['name']}")
    if new["scope"]["unmapped"]:
        problems.append(f"官方映射缺 orgId: {new['scope']['unmapped']}")
    cross = cross_check_securities(new)
    if cross.get("name_mismatch"):
        problems.append(f"与证券业白名单名称不一致: {cross['name_mismatch']}")
    if problems:
        print("CHECK_MISMATCH")
        for p in problems:
            print(" -", p)
        return 1
    print(f"CHECK_OK count={new['count_total']} "
          f"org_prefixes={sorted({e['org_prefix'] for e in new['whitelist']})} "
          f"exchanges={sorted({e['exchange'] for e in new['whitelist']})} "
          f"overlap_with_securities={cross.get('overlap_count')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="与 latest.json 对账（幂等验证）")
    args = ap.parse_args()
    if args.check:
        return check_against_latest()

    doc = build_whitelist()
    cross = cross_check_securities(doc)
    doc["cross_check"] = {"securities_whitelist": cross}
    paths = write_outputs(doc)

    scope = doc["scope"]
    print(f"BK0475 {scope['board_name']}: {scope['count']} 家（H 股排除计数 {scope['h_share_excluded']}）")
    print("orgId 前缀分布: " + ", ".join(
        f"{p}×{n}" for p, n in sorted(
            (p, sum(1 for e in doc['whitelist'] if e['org_prefix'] == p))
            for p in {e['org_prefix'] for e in doc['whitelist']})))
    print("交易所分布: " + ", ".join(
        f"{x}×{n}" for x, n in sorted(
            (x, sum(1 for e in doc['whitelist'] if e['exchange'] == x))
            for x in {e['exchange'] for e in doc['whitelist']})))
    if cross.get("available"):
        print(f"与证券业白名单交集 {cross['overlap_count']} 家，名称不一致 "
              f"{len(cross['name_mismatch'])} 条")
    for p in paths:
        print("written:", p.relative_to(_REPO))
    return 0 if not scope["unmapped"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
