#!/usr/bin/env python
"""银行业定期报告 ingest 驱动器（awaken-banking-report-ingest 3.1 / 5.1）。

链路：巨潮 category 检索 → 条数校验/去重 → static.cninfo PDF 下载（带磁盘缓存）
      → 文本抽取 → 目录切章 → report_documents / report_sections 落库。

范围口径（白名单）来自 `scripts/bank_whitelist.py` 的
`output/bank-whitelist/latest.json`；报告期默认 FY2024-2026 四类定期报告。

去重与拦截规则（spec Requirement「定期报告 ingest SHALL 规模唤醒并留验收痕迹」）：
  · 摘要（`摘要`）不入库——正文是年报/半年报本体
  · 英文版（`英文`）不入库
  · A+H 双版本按 `含 H股公告` / `H股` 标题标记去重（A 股版优先，H 版零入库）
  · 单 (银行, 类型, 报告期) 命中 >`--max-hits` 条视为过滤失效，拦下不入库并留痕
  · 缺刊（该期无公告）如实记 `missing`，不补造

用法（fd-cn-report venv）：
  python3 scripts/bank_ingest.py --pilot                    # 5 家试点 × FY2024-2026 × 四类
  python3 scripts/bank_ingest.py --wave state-owned          # 国有大行
  python3 scripts/bank_ingest.py --codes 601398,600036 --years 2025
  python3 scripts/bank_ingest.py --pilot --dry-run           # 只检索不下载

产物：
  out/bank-ingest/run-<timestamp>.json   逐 (银行,类型,报告期) 结果
  .cache/reports/                        PDF + 文本 + 目录缓存（--drop-pdf 可弃原文）
"""
from __future__ import annotations

import argparse
import re
import json
import sys
import time
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO / ".env")
load_dotenv(_REPO / ".env.local", override=True)

import cninfo_client as CN  # noqa: E402
import cnreport_tools as T  # noqa: E402
import report_cache  # noqa: E402
from cnreport_database import get_db, make_report_id  # noqa: E402

WHITELIST = _REPO / "output" / "bank-whitelist" / "latest.json"
OUT_DIR = _REPO / "out" / "bank-ingest"

FORMS = ["年度报告", "半年度报告", "第一季度报告", "第三季度报告"]

#: 试点：覆盖三种 orgId 前缀形态与 A+H 双版本、国有大行/股份行各取代表
PILOT = ["601398", "601288", "601939", "600036", "000001"]

#: 分波（W4）：国有大行 → 股份行 → 城农商行
WAVES = {
    "state-owned": ["601398", "601288", "601939", "601988", "601328", "601658"],
    "joint-stock": ["600036", "601166", "600000", "601998", "600016", "600015",
                    "000001", "601818", "601169", "601009", "600926", "002142"],
}

#: 请求间隔（侦察实测阈值 ≥1.2s）
REQUEST_INTERVAL = 1.3

_EXCLUDE_TITLE_MARKERS = ("摘要", "英文", "English")
_H_SHARE_MARKERS = ("含 H股公告", "含H股公告", "H股公告", "H股版本")

#: 报告类型的中文同义词，**长词在前**（否则 "半年报" 会被 "年报" 抢先匹配）。
#: 实测两处必须兼容：平安银行等深市行用「三季度报告」「一季度报告」，
#: 建设银行用「半年报」（2024 年半年报标题就是"建设银行半年报"）。
#: 引擎 `_form_from_title` 只认「第三季度报告/半年度报告」，走 form= 路径会把
#: 这些正文公告整类过滤成 0 条（实测 000001 三季报 0 条、601939 半年报 0 条），
#: 故驱动器改走 category= 并在本地按同义词判型，不动引擎。
FORM_SYNONYMS: list[tuple[str, tuple[str, ...]]] = [
    ("半年度报告", ("半年度报告", "半年报", "中期报告")),
    ("第一季度报告", ("第一季度报告", "一季度报告", "第一季度", "一季度")),
    ("第三季度报告", ("第三季度报告", "三季度报告", "第三季度", "三季度")),
    ("年度报告", ("年度报告", "年报")),
]

_FORM_CATEGORY = {
    "年度报告": "category_ndbg_szsh",
    "半年度报告": "category_bndbg_szsh",
    "第一季度报告": "category_yjdbg_szsh",
    "第三季度报告": "category_sjdbg_szsh",
}


def _form_of_title(title: str) -> str:
    """按同义词表判定公告属于哪类定期报告（长词优先，避免「半年报」判成年报）。"""
    flat = title.replace("　", "").replace(" ", "")
    for form, words in FORM_SYNONYMS:
        if any(w in flat for w in words):
            return form
    return ""


def _fiscal_year_from_publish(form: str, published: str) -> int | None:
    """按公告发布日推断财年：年报次年披露（-1），半年报/季报同年披露。

    必须留这条回退：建行 2024 年半年报的标题就是「建设银行半年报」——不带年份，
    只按标题匹配年份会把正文公告整类丢掉（实测 601939 FY2024 半年报 0 条）。
    """
    try:
        year = int(str(published)[:4])
    except (TypeError, ValueError):
        return None
    return year - 1 if form == "年度报告" else year


def _load_whitelist() -> dict[str, dict]:
    if not WHITELIST.exists():
        raise SystemExit(f"白名单缺失：{WHITELIST} —— 先跑 scripts/bank_whitelist.py")
    doc = json.loads(WHITELIST.read_text(encoding="utf-8"))
    return {e["code"]: e for e in doc["whitelist"]}


def _is_h_share(title: str) -> bool:
    flat = title.replace("　", " ").replace(" ", "")
    return any(m.replace(" ", "") in flat for m in _H_SHARE_MARKERS)


def _pick_report(rows: list[dict], form: str, fiscal_year: int) -> tuple[dict | None, dict]:
    """从 category 结果里挑正文报告，返回 (选中行, 筛选留痕)。

    走 category 通道后必须自己判型：category 会连摘要、H 股版、别类定期报告一起
    返回（实测 601939 半年报 category 6 条里混着 H 股公告与年报摘要），故按
    「同义词判型 == 请求类型」+"标题含报告期"+"非摘要/英文/H 股"三重过滤。
    """
    trace = {"raw": len(rows), "dropped_summary": 0, "dropped_english": 0,
             "dropped_h_share": 0, "dropped_other_form": 0, "dropped_other_year": 0,
             "candidates": []}
    keep: list[dict] = []
    for row in rows:
        title = row.get("title") or ""
        if any(m in title for m in _EXCLUDE_TITLE_MARKERS):
            trace["dropped_summary" if "摘要" in title else "dropped_english"] += 1
            continue
        if _is_h_share(title):
            trace["dropped_h_share"] += 1
            continue
        if _form_of_title(title) != form:
            trace["dropped_other_form"] += 1
            continue
        flat = title.replace(" ", "")
        if str(fiscal_year) in flat:
            pass
        elif (re.search(r"20\d{2}", flat) is None
              and _fiscal_year_from_publish(form, row.get("published")) == fiscal_year):
            # 标题不含年份（如「建设银行半年报」）→ 按发布日推财年，且标题里不得
            # 出现任何别的年份，避免把别年同名公告当成目标期
            trace.setdefault("matched_by_publish_date", 0)
            trace["matched_by_publish_date"] += 1
        else:
            trace["dropped_other_year"] += 1
            continue
        keep.append(row)
        trace["candidates"].append(flat)
    if not keep:
        return None, trace
    return keep[0], trace


def _normalized_index(text: str) -> tuple[str, list[int]]:
    """去掉所有空白后的正文 + 「规范化下标 → 原始下标」映射。

    目录标题与正文标题的空格写法常不一致（目录 `8. 1`、正文 `8.1`），
    直接 `text.find` 会 884 条里只命中 52 条；规范化后 884/884 命中。
    映射表让字数仍按**原始**字符数统计，不用规范化后的长度冒充。
    """
    chars: list[str] = []
    index: list[int] = []
    for pos, ch in enumerate(text):
        if ch.isspace():
            continue
        chars.append(ch)
        index.append(pos)
    index.append(len(text))  # 末尾哨兵，供「到文末」切片取原始长度
    return "".join(chars), index


def _section_rows(text: str, info: dict) -> tuple[list[dict], int]:
    """目录条目 → 可**唯一定位**的章节行（按正文位置排序）+ 被丢弃条目数。

    银行年报实测：引擎 `parse_outline` 给出的 884 条里 830 条是点号编号碎片
    （`8. 3`、`8. 3.10`），在正文里作为交叉引用反复出现、也定位不到唯一章节。
    把这类碎片写成 report_sections 行等于给下游一张假地图，所以本驱动器只落
    **可唯一定位**的条目：

      · 带 `page` 锚的报表检测项（资产负债表/利润表/现金流量表…）——一定有
      · 普通标题段（长度 ≥4 且规范化后在全文中只出现 1 次）——章/节/「一、…」类

    同一位置只留一条：outline 里重复标题会让两条各算一遍同一段跨度，把总字数
    撑成正文的 1.8 倍。被丢弃条目数返回给调用方进运行留痕——不是没解析，是解析
    产物不可用作章节。
    """
    entries = info.get("enriched_outline")
    if not entries:
        entries = T.parse_outline(text)

    ntext, index = _normalized_index(text)
    norm = lambda s: re.sub(r"\s+", "", s)  # noqa: E731

    kept: dict[int, tuple[int, str]] = {}  # 位置 → (level, title)
    dropped = 0
    for entry in entries:
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        level = int(entry.get("level") or 1)
        needle = norm(title)
        anchored = bool(entry.get("page"))
        if not anchored and (len(needle) < 4 or ntext.count(needle) != 1):
            dropped += 1
            continue
        pos = ntext.find(needle) if needle else -1
        if pos < 0:
            dropped += 1
            continue
        kept.setdefault(pos, (level, title[:500]))

    rows: list[dict] = []
    for ordinal, (pos, (level, title)) in enumerate(sorted(kept.items()), 1):
        rows.append({"ordinal": ordinal, "level": level, "title": title, "_pos": pos})
    for i, row in enumerate(rows):
        end = rows[i + 1]["_pos"] if i + 1 < len(rows) else len(index) - 1
        row["char_count"] = max(0, index[end] - index[row["_pos"]])
    for row in rows:
        row.pop("_pos", None)
    return rows, dropped


def _scrub_outlines(stem: str | None) -> str:
    """入库后立刻修该报告的缓存大纲标题；返回简短留痕（空=无需修/失败）。

    只改「被选择器点名 + 当前切出目录页」的条目（见 scripts/scrub_bank_outlines.py
    的说明）；失败不影响入库主流程。
    """
    if not stem:
        return ""
    try:
        import scrub_bank_outlines as S
    except Exception:
        return ""
    text_path = report_cache.cache_dir() / f"{stem}.txt"
    if not text_path.exists():
        return ""
    try:
        text = text_path.read_text(encoding="utf-8", errors="replace")
        total = 0
        for kind in S.OUTLINE_KINDS:
            path = report_cache.cache_dir() / f"{stem}{kind}"
            if not path.exists():
                continue
            entries = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                continue
            offsets = None
            po = report_cache.cache_dir() / f"{stem}.page_offsets.json"
            if po.exists():
                try:
                    raw = json.loads(po.read_text(encoding="utf-8"))
                    offsets = raw if isinstance(raw, list) else raw.get("offsets")
                except Exception:
                    offsets = None
            entries, fixed = S.repair_entries(text, entries, S.DEFAULT_SECTIONS, offsets)
            if fixed:
                path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
                total += fixed
        return f"outline_titles_fixed={total}" if total else ""
    except Exception as exc:  # 净化是增益步骤，失败不阻断入库
        return f"outline_scrub_failed: {type(exc).__name__}"


def _prune_sections(db, report_id: str, keep: int) -> int:
    """删掉本报告 ordinal > keep 的残留章节行。

    `upsert_section` 只按 (report_id, ordinal) 覆盖，不清多余行：同一份报告换一版
    切章策略后条目变少时，旧的高序号行会留在表里，章节数与字数统计全部虚高
    （实测 375 条新切章后面上仍是 884 条、总字数 73 万 > 正文 40 万）。
    """
    from sqlalchemy import text as _sql

    session = db.get_session()
    try:
        res = session.execute(
            _sql("DELETE FROM report_sections WHERE report_id = :rid AND ordinal > :keep"),
            {"rid": report_id, "keep": keep},
        )
        session.commit()
        return int(res.rowcount or 0)
    finally:
        session.close()


def ingest_one(bank: dict, form: str, fiscal_year: int, *, dry_run: bool,
               drop_pdf: bool, max_hits: int, db) -> dict:
    code, name, org_id = bank["code"], bank["name"], bank["org_id"]
    record = {"code": code, "name": name, "form": form, "fiscal_year": fiscal_year,
              "status": "", "report_id": "", "title": "", "sections": 0,
              "chars": 0, "pdf_bytes": 0, "note": ""}
    try:
        # 走 category 通道（不走 form=）：form= 路径依赖引擎 `_form_from_title`，
        # 它只认「第三季度报告/半年度报告」全称，深市「三季度报告」「一季度报告」
        # 与建行「半年报」会被整类过滤成 0 条。类型判定改在 `_pick_report` 本地做。
        rows = CN.query_announcements(code, org_id, category=_FORM_CATEGORY[form],
                                      year=fiscal_year, limit=25)
    except Exception as exc:
        record.update(status="query_failed", note=f"{type(exc).__name__}: {exc}"[:300])
        return record

    chosen, trace = _pick_report(rows, form, fiscal_year)
    record["hits"] = trace
    if trace["raw"] > max_hits:
        # category 静默降级 = 混杂公告灌入，拦下不猜
        record.update(status="blocked_category_drift",
                      note=f"原始命中 {trace['raw']} 条 > 上限 {max_hits}，判为过滤失效，不入库")
        return record
    if chosen is None:
        record.update(status="missing", note="该报告期无正文公告（缺刊如实留痕）")
        return record

    url = chosen.get("pdf_url") or ""
    record["title"] = chosen.get("title") or ""
    if not url:
        record.update(status="no_pdf_url", note=str(chosen)[:200])
        return record
    if dry_run:
        record.update(status="dry_run", note=url)
        return record

    report_id = make_report_id(url, name, fiscal_year, form)
    record["report_id"] = report_id
    db.upsert_document(report_id, url, name, code, fiscal_year, parse_status="fetched")

    try:
        text, info = report_cache.get_or_fetch(
            url, stock_code=code, year=fiscal_year, form=form,
            announcement_id=chosen.get("announcement_id"),
        )
    except Exception as exc:
        db.upsert_document(report_id, url, name, code, fiscal_year, parse_status="fetch_failed")
        record.update(status="fetch_failed", note=f"{type(exc).__name__}: {exc}"[:300])
        return record

    pdf_path = report_cache.cache_dir() / f"{info.get('stem')}.pdf"
    if pdf_path.exists():
        record["pdf_bytes"] = pdf_path.stat().st_size
    record["chars"] = len(text or "")
    if not text or len(text.strip()) < 200:
        db.upsert_document(report_id, url, name, code, fiscal_year,
                           raw_path=str(pdf_path) if pdf_path.exists() else None,
                           parse_status="empty_text")
        record.update(status="empty_text", note="文本层为空（扫描件？）")
        return record

    sections, dropped = _section_rows(text, info)
    # 大纲净化：PDF 书签标题带排版空隙（`5. 6.4 流动性风险` vs 正文 `5.6.4 流动性风险`），
    # 抽取时 `_find_section_start` 找不到 → 退化成首 token「5.」→ 切出目录页，
    # 目标指标落在 24k 窗口外被判「未披露」。入库后立刻修缓存大纲（幂等，只改坏条目）。
    scrub_note = _scrub_outlines(info.get("stem"))
    db.upsert_document(report_id, url, name, code, fiscal_year,
                       raw_path=str(pdf_path) if pdf_path.exists() else None,
                       parse_status="parsing")
    for sec in sections:
        db.upsert_section(report_id, sec["ordinal"], sec["level"], sec["title"],
                          sec["char_count"])
    pruned = _prune_sections(db, report_id, len(sections))
    db.upsert_document(report_id, url, name, code, fiscal_year,
                       raw_path=str(pdf_path) if pdf_path.exists() else None,
                       parse_status="ok" if sections else "no_outline")
    record.update(status="ok" if sections else "no_outline", sections=len(sections),
                  sections_dropped=dropped, sections_pruned=pruned)
    if dropped:
        record["note"] = f"目录 {len(sections) + dropped} 条中 {dropped} 条为编号碎片/不可唯一定位，未冒充章节"
    if drop_pdf and pdf_path.exists():
        pdf_path.unlink()
        record["note"] = "pdf dropped after text cache"
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pilot", action="store_true", help="5 家试点")
    ap.add_argument("--wave", choices=sorted(WAVES) + ["rest"], help="按波次取名单")
    ap.add_argument("--codes", default="", help="逗号分隔代码（覆盖 --pilot/--wave）")
    ap.add_argument("--years", default="2024,2025,2026", help="报告期（财年）列表")
    ap.add_argument("--forms", default=",".join(FORMS), help="报告类型（中文名）")
    ap.add_argument("--max-hits", type=int, default=6, help="单期命中上限，超过即拦下")
    ap.add_argument("--drop-pdf", action="store_true", help="文本落缓存后删除 PDF 原文")
    ap.add_argument("--dry-run", action="store_true", help="只检索不下载")
    args = ap.parse_args()

    whitelist = _load_whitelist()
    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    elif args.pilot:
        codes = PILOT
    elif args.wave == "rest":
        # 第三波（城农商行）＝白名单减去前两波，代码不硬编码，随白名单变动自动跟随
        used = {c for v in WAVES.values() for c in v}
        codes = sorted(c for c in whitelist if c not in used)
    elif args.wave:
        codes = WAVES[args.wave]
    else:
        codes = sorted(whitelist)

    unknown = [c for c in codes if c not in whitelist]
    if unknown:
        raise SystemExit(f"不在白名单内：{unknown}")
    years = [int(y) for y in args.years.split(",") if y.strip()]
    forms = [f.strip() for f in args.forms.split(",") if f.strip()]

    db = get_db()
    db.init_db()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    total = len(codes) * len(forms) * len(years)
    idx = 0
    for code in codes:
        bank = whitelist[code]
        for form in forms:
            for fy in years:
                idx += 1
                print(f"[{idx}/{total}] {code} {bank['name']} {form} FY{fy} ...",
                      flush=True)
                row = ingest_one(bank, form, fy, dry_run=args.dry_run,
                                 drop_pdf=args.drop_pdf, max_hits=args.max_hits, db=db)
                results.append(row)
                print(f"    {row['status']} sections={row['sections']} "
                      f"chars={row['chars']} pdf={row['pdf_bytes']}B {row['note'][:60]}",
                      flush=True)
                if not args.dry_run:
                    time.sleep(REQUEST_INTERVAL)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"run-{stamp}.json"
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": {"codes": codes, "years": years, "forms": forms,
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
