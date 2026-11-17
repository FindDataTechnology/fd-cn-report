#!/usr/bin/env python
"""农业定期报告 ingest 驱动（awaken-agriculture-report-ingest 3.1–3.4 / 5.1–5.2）。

链路与银行业那版**完全同一条**（巨潮 category 检索 → 条数校验/去重 → static.cninfo
PDF 下载（磁盘缓存）→ 文本抽取 → 目录切章 → `report_documents`/`report_sections` 落库）。
这里**不重写**取数/切章/入库机械，直接复用 `scripts/bank_ingest.py` 的实现——
同一套机器服务两条行业线，改一处两条线一起受益（写第五份副本才是真债）。

本文件只负责农业侧的三件事：白名单来源、试点/分波选型、以及银行的
「目录标题净化」不适用于农业年报（那是按银行年报章节写的选择器），显式关掉。

范围口径来自 `fd-industry-data/docs/agri-report-whitelist.json` 的 `a_share`
（101 家，orgId 全齐；农资排除 3 家），报告期为 FY2024–2026 四类定期报告。

用法（fd-cn-report venv）::

    python3 scripts/agri_ingest.py --pilot --dry-run     # 只检索，不下载
    python3 scripts/agri_ingest.py --pilot               # 5 家试点 × 4 类 × 3 年
    python3 scripts/agri_ingest.py --wave w1             # 分波回补（5.1）
    python3 scripts/agri_ingest.py --codes 002714 --years 2024 --forms 年度报告

产物：``out/agri-ingest/run-<timestamp>.json``（逐 (公司,类型,报告期) 结果）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO / ".env")
load_dotenv(_REPO / ".env.local", override=True)

import bank_ingest as B  # noqa: E402  复用同一套 ingest 机械（见模块 docstring）
from cnreport_database import get_db  # noqa: E402

#: 农业白名单（跨仓路径：本仓只读，不复制一份会漂移的名单）
DEFAULT_WHITELIST = (Path("/Users/chengsishi/finddata/fd-industry-data/docs/"
                          "agri-report-whitelist.json"))
OUT_DIR = _REPO / "out" / "agri-ingest"

#: 3.1 试点：五类业务各一家，且**故意覆盖 5 种 orgId 前缀形态**
#: （9900 / gfbj / nssc / gssz / gssh——orgId 绝不能按交易所前缀拼，实测深市混用
#: 9900 与 gssz、沪市混用 9900 与 gssh，所以选型要看前缀而不是看板块）。
#: gshk 前缀全宇宙只有 1 家（605198 安德利，农产品加工），留到 W4 分波覆盖。
PILOT = [
    ("002714", "生猪养殖", "9900"),
    ("300967", "禽养殖", "gfbj"),
    ("001366", "饲料", "nssc"),
    ("000998", "种业", "gssz"),
    ("600598", "种植", "gssh"),
]

#: 5.1 四波：按业务形态分，不按市值分（市值分层会漏掉小市值但披露形态特殊的公司）。
#: 波次名沿用 spec 的四波叙事，但**取值必须用白名单里的真实 segment 值**
#: （白名单只有粗板块：养殖/饲料/种植/动保/渔业/林业/农产品加工；猪与禽拆不开，
#: 故 w1「生猪养殖→禽养殖」合并成 `养殖`，w3「种业与种植」合并成 `种植`）。
WAVES = {
    "w1": ("养殖",),
    "w2": ("饲料",),
    "w3": ("种植",),
    "w4": ("动保", "渔业", "林业", "农产品加工"),
}

#: 农业年报没有银行那套「5.6.4 流动性风险」章节选择器，关掉银行的目录净化，
#: 免得按银行口径改坏农业报告的大纲标题。
B._scrub_outlines = lambda stem: ""  # noqa: SLF001


#: 农业侧公告挑选包装（**不改银行线的代码**，只在本驱动器里换掉挑选函数）。
#: 实测两类噪声会让「命中过多」守卫误拦：
#:   ① 「关于更正《2024年年度报告》的公告」——是**通知**不是报告本体，入库就是错文件；
#:   ② 同一期同时有「原版」与「（更正后）」——应取**更正后**版本。
#: 例：600965 2024 年报 category 原始命中 8 条 = 摘要 2 + 更正公告 1 + 原版 1 + 更正后 1 + 别年 3，
#: 真正的候选只有 2 条，却被 `raw > max_hits` 判成「过滤失效」整组不入库。
_ORIG_PICK = B._pick_report


def _pick_report(rows, form, fiscal_year):
    clean = []
    for row in rows:
        title = (row.get("title") or "").replace("　", "").replace(" ", "")
        if "更正" in title and "更正后" not in title:
            continue                      # 更正「公告」不是报告本体
        clean.append(row)
    # 更正后版本排到最前（同一期有原版+更正后时取更正后）
    clean.sort(key=lambda r: 0 if "更正后" in (r.get("title") or "") else 1)
    return _ORIG_PICK(clean, form, fiscal_year)


B._pick_report = _pick_report  # noqa: SLF001


def _load_whitelist(path: Path) -> dict[str, dict]:
    if not path.is_file():
        raise SystemExit(f"白名单缺失：{path} —— 先跑 fd-industry-data/scripts/agri_report_whitelist.py")
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = doc.get("a_share") or []
    if not rows:
        raise SystemExit(f"白名单 a_share 为空：{path}")
    return {r["code"]: {"code": r["code"], "name": r["name"],
                        "org_id": r.get("orgId"), "segment": r.get("segment")}
            for r in rows if r.get("orgId")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--whitelist", default=str(DEFAULT_WHITELIST))
    ap.add_argument("--pilot", action="store_true", help="5 家试点（覆盖 5 种 orgId 前缀）")
    ap.add_argument("--wave", choices=sorted(WAVES) + ["rest"], help="按业务波次取名单")
    ap.add_argument("--codes", default="", help="逗号分隔代码（覆盖 --pilot/--wave）")
    ap.add_argument("--years", default="2024,2025,2026")
    ap.add_argument("--forms", default=",".join(B.FORMS))
    ap.add_argument("--max-hits", type=int, default=6, help="单期命中上限，超过即拦下")
    ap.add_argument("--drop-pdf", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    whitelist = _load_whitelist(Path(args.whitelist))

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    elif args.pilot:
        codes = [c for c, _seg, _pre in PILOT]
        # 选型自证：前缀必须与声明一致，否则「覆盖不同前缀形态」就是空话
        bad = [(c, whitelist[c]["org_id"][:4], pre) for c, _s, pre in PILOT
               if c in whitelist and not whitelist[c]["org_id"].startswith(pre)]
        if bad:
            raise SystemExit(f"试点前缀与声明不符（白名单变动？）：{bad}")
        missing = [c for c, _s, _p in PILOT if c not in whitelist]
        if missing:
            raise SystemExit(f"试点不在农业白名单内：{missing}")
    elif args.wave == "rest":
        used = set(PILOT_CODE for PILOT_CODE, _s, _p in PILOT)
        used |= {c for segs in ([WAVES[k] for k in ("w1", "w2", "w3", "w4")]
                               ) for seg in segs
                 for c, r in whitelist.items() if r["segment"] == seg}
        codes = sorted(c for c in whitelist if c not in used)
    elif args.wave:
        segs = WAVES[args.wave]
        codes = sorted(c for c, r in whitelist.items() if r["segment"] in segs)
        if not codes:
            raise SystemExit(f"波次 {args.wave} 在名单里 0 家（segment 口径可能变了）")
    else:
        codes = sorted(whitelist)

    unknown = [c for c in codes if c not in whitelist]
    if unknown:
        raise SystemExit(f"不在农业白名单内：{unknown}")
    years = [int(y) for y in args.years.split(",") if y.strip()]
    forms = [f.strip() for f in args.forms.split(",") if f.strip()]

    db = get_db()
    db.init_db()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    total = len(codes) * len(forms) * len(years)
    idx = 0
    for code in codes:
        company = whitelist[code]
        for form in forms:
            for fy in years:
                idx += 1
                print(f"[{idx}/{total}] {code} {company['name']} {form} FY{fy} ...",
                      flush=True)
                row = B.ingest_one(company, form, fy, dry_run=args.dry_run,
                                   drop_pdf=args.drop_pdf, max_hits=args.max_hits, db=db)
                row["segment"] = company.get("segment")
                results.append(row)
                print(f"    {row['status']} sections={row['sections']} "
                      f"chars={row['chars']} pdf={row['pdf_bytes']}B {row['note'][:60]}",
                      flush=True)
                if not args.dry_run:
                    time.sleep(B.REQUEST_INTERVAL)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"run-{stamp}.json"
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_for": "awaken-agriculture-report-ingest 3.2 / 5.1",
        "scope": {"codes": codes, "years": years, "forms": forms,
                  "pilot": args.pilot, "wave": args.wave,
                  "dry_run": args.dry_run, "drop_pdf": args.drop_pdf},
        "status_counts": counts,
        "total_pdf_bytes": sum(r["pdf_bytes"] for r in results),
        "results": results,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n=== 状态汇总 ===")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    print(f"PDF 合计 {payload['total_pdf_bytes'] / 1e6:.1f} MB")
    print("written:", out.relative_to(_REPO))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
