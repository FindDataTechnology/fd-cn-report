#!/usr/bin/env python
"""修大纲标题与正文写法不一致（awaken-banking-report-ingest 3.2）。

**问题**：PDF 书签/正则解析出的大纲标题保留了**排版空隙**（`5. 6.4 流动性风险`、
`5. 7.3资本充足率和杠杆率`），而正文文字层是紧凑写法（`5.6.4 流动性风险`）。
`extract_section_text` 用 `_find_section_start(text, entry["title"])` 在正文里找标题，
找不到就退化成**首 token**（`entry["title"].split()[0]` → `"5."`）再找一次，于是切出
从「5.2 战略执行情况……」开始的目录段（实测农行 150201 字符，全是点号目录行）。

后果不是「抽不出」而是「切错段」：农行 2025 年报的
    杠杆率 6.28%、资本充足率 17.93%、流动性覆盖率均值 133.5%、净稳定资金比例 132.28%
全部落在被切出的目录段之外，LLM 在 24000 字符窗口里看不到 → 返回 null。
三个指标因此假性「未披露」。

**修法（只改派生数据，不动引擎）**：把大纲标题替换成**正文里真实可定位的写法**：
  1. 先试「数字间的空格去掉」：`5. 6.4 流动性风险` → `5.6.4 流动性风险`
  2. 再试「全去空白」：`8. 1 集团架构` → `8.1集团架构`
  3. 再试「数字后去空白」
只有能在正文里通过 `_find_section_start` 的标题守卫（跳过点号目录行、跳过「下一行是
页码」的目录行）命中的写法才采用，否则保持原样——不乱改。

实测（601288，enriched 990 条）：885 条修好，98 条仍不可定位（多为 `2. 88  23,926,450`
这类表格数字碎片，以及 `合并资产负债表` 等靠 `page` 锚切片、不依赖标题定位的报表项）。

**幂等**：已可定位的标题不碰；重复跑 `fixed=0`。改动前把原文件备份到
`output/bank-rules/outlines-<stamp>/`。

用法：
  python3 scripts/scrub_bank_outlines.py --dry-run
  python3 scripts/scrub_bank_outlines.py                      # 全部缓存报告
  python3 scripts/scrub_bank_outlines.py --codes 601288,601939
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

CACHE_DIR = _REPO / ".cache" / "reports"
OUT_DIR = _REPO / "output" / "bank-rules"
OUTLINE_KINDS = (".outline.json", ".outline_enriched.json")


def _whole_line_hit(text: str, title: str) -> bool:
    """标题必须**整行**命中：行内只允许标题本身（可带尾随空白）。

    否则会把「目录行」也当成正文标题——实测 `'3. 4.2 杠杆率            62'` 这类
    目录条目（页码在标题字符串内部）在清掉空隙后就能通过 `_find_section_start`
    的守卫（守卫只看标题**之后**的文字），一改反而把目录行变成可命中项。
    """
    import cnreport_tools as T

    pos = T._find_section_start(text, title)
    if pos == -1:
        return False
    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    line = text[line_start:line_end if line_end != -1 else len(text)].strip()
    return line == title.strip()


_PURE_NUMERIC_RE = re.compile(r"^[\d.\s,()%\-－—]+$")

#: 默认要修的段名＝监管指标选择器链里点名的那些段（与 repair_bank_indicator_selectors.py
#: 保持同源，避免两处清单漂移）；其余条目一律不动。
try:
    from repair_bank_indicator_selectors import (  # noqa: E402  (脚本同目录)
        COMPANY_SELECTORS,
        SELECTOR_CHAINS,
    )

    DEFAULT_SECTIONS: list[str] = sorted(
        {s for chain in SELECTOR_CHAINS.values() for s in chain}
        | {s for m in COMPANY_SELECTORS.values() for titles in m.values() for s in titles}
    )
except Exception:  # pragma: no cover - 单跑本脚本时也能工作
    DEFAULT_SECTIONS = [
        "财务指标", "主要财务指标", "财务摘要", "盈利能力指标", "财务概要",
        "贷款迁徙率", "主要监管指标", "贷款质量", "贷款质量分析",
        "信用风险管理", "贷款资产质量分析", "（1）发放贷款和垫款五级分类情况",
        "流动性风险", "流动性风险分析", "流动性风险管理", "流动性风险指标",
        "净稳定资金比例", "杠杆率", "资本充足率及杠杆率情况", "资本充足率情况",
    ]


def _variants(title: str):
    """按「最贴近原文」的顺序给出候选写法。"""
    yield re.sub(r"(?<=[\d.])\s+(?=[\d.])", "", title)  # 5. 6.4 → 5.6.4
    yield re.sub(r"(?<=[\d.])\s+", "", title)           # 数字后去空白
    yield re.sub(r"\s+", "", title)                      # 全去空白


_TOC_RE = re.compile(r"(?:\.{3,}|…{2,})")

#: 已知「标题带 PDF 空隙、切片不是点号目录但起点错」的标题——实测需要点名修，
#: 不能靠「不可定位就改名」的宽判据（宽判据会让改名条目成为别的段的截断边界，
#: 把 600036 的六个锚顶成 nan：不良贷款余额/流动性覆盖率/四项迁徙率）。
_FORCE_REPAIR_TITLES = ("关于重点领域资产质量", "重组贷款情况")


def _is_toc_sludge(body: str) -> bool:
    """切片开头是不是目录页（满是点号引导行）。

    这是「该条目坏了」的直接证据：标题在正文里定位不到 → `extract_section_text`
    退化成用首 token（`"5."`）定位 → 从目录页开始切。实测 601288「5. 6.4 流动性风险」
    切出 150201 字符的点号目录行，真值全在 24k 窗口之外。
    """
    head = (body or "")[:400]
    return len(_TOC_RE.findall(head)) >= 3


def repair_entries(text: str, entries: list[dict], sections: list[str],
                   page_offsets=None) -> tuple[list[dict], int]:
    """修标题，两个条件同时满足才动：**链里点名要打** 且 **当前切出来是目录页**。

    为什么不能全量改名：`extract_section_text` 把一段切到**下一个可定位的条目**为止。
    一旦把别的条目也改成可定位写法，父节就会被截到自己的第一个子标题（实测 600036：
    「流动性风险」从 156813 字符缩成 73427/722，流动性覆盖率表落到切片外，该行从
    17/17 掉到 11/17）。所以：
      · 没被点名 → 不动（它是别人切片的截断边界）
      · 点名了但切得正常 → 不动（改了反而缩短别人的切片）
      · 点名了且切出目录页 → 改（这个条目对本轮抽取就是坏的）
    """
    import cnreport_tools as T

    targets = {re.sub(r"\s+", "", s) for s in sections if s}
    fixed = 0
    for entry in entries:
        title = (entry.get("title") or "").strip()
        if not title or _PURE_NUMERIC_RE.match(title):
            continue  # 空标题 / 「2. 88」「100. 0」这类表格数字碎片，不碰
        if len(title) > 40:
            continue  # 长行不是标题（实测有把「5. 42%；成本收入比27.34%…」正文句当条目）
        norm = re.sub(r"\s+", "", title)
        if not any(t and t in norm for t in targets):
            continue  # 没被点名的段不动——它是别的段的截断边界，改了会缩短别人的切片
        if _whole_line_hit(text, title):
            continue  # 已可定位
        # 闸门：①切片是点号目录页（sludge），或 ②标题命中 _FORCE_REPAIR_TITLES 白名单。
        # **不能**放宽成「不可定位就改名」：实测 600036 一次改 7 条后，新可定位的条目变成
        # 别的段的截断边界，六个锚（不良贷款余额/流动性覆盖率/四项迁徙率）立刻变 nan。
        need = any(k in title for k in _FORCE_REPAIR_TITLES)
        if not need:
            slice_now = T.extract_section_text(text, entries, entry, page_offsets=page_offsets) or ""
            if not slice_now or not _is_toc_sludge(slice_now):
                continue
        for candidate in _variants(title):
            if not candidate or candidate == title or _PURE_NUMERIC_RE.match(candidate):
                continue
            if _whole_line_hit(text, candidate):
                entry["title"] = candidate
                fixed += 1
                break
    return entries, fixed


_SENTENCE_RE = re.compile(r"[。；;]")


def drop_junk_entries(text: str, entries: list[dict]) -> tuple[list[dict], int]:
    """摘掉「句子碎片」型大纲条目（不是标题，却会被 selector 子串匹配抢走）。

    实测（601398 2025 半年报）：大纲里有一条
    `3. 43 万亿元，不良贷款率1.49%，拨备覆盖率211.97%；资本充足率15.58%。`
    它含「资本充足率」，于是 `杠杆率/资本充足率` 的链子串匹配到它 → 切出目录页（79249
    字符，开头全是点号），真值（杠杆率 7.49%、资本充足率 19.54%）落在窗口外 → null。
    更危险的是句中的 **15.58% 是分行口径**，一旦被取到就是错值。

    判据（两轮收窄后的终态，2026-11-08 实测）：标题**含「。」** 且整行不可命中。
      · 只含「；」不算——那是段落标题的常见分隔符，误删会移动切片边界
        （早期用「len>40 或含 。；」一次删掉 30-40 条，把 6 条 golden 锚顶成错值）。
      · 必须"整行不可命中"——脚注定义行（`8、 不良贷款余额…除以发放贷款和垫款总额…`）
        在正文里定位不到，从来不是任何切片的截断边界，所以删它**不改任何既有切片**，
        只消除「选择器子串被脚注抢走」这类误命中。实测每份报告 6–24 条。
    """
    kept: list[dict] = []
    dropped = 0
    for entry in entries:
        title = (entry.get("title") or "").strip()
        if title and ("。" in title) and not _whole_line_hit(text, title):
            dropped += 1
            continue
        kept.append(entry)
    if dropped:  # 重排 ordinal，保持连续（下游按 ordinal 排序/比较）
        for i, entry in enumerate(kept, 1):
            entry["ordinal"] = i
    return kept, dropped


def _stems(codes: list[str] | None) -> list[str]:
    txts = sorted(CACHE_DIR.glob("*.txt"))
    if codes:
        txts = [p for p in txts if any(p.name.startswith(f"{c}_") for c in codes)]
    return [str(p)[:-4] for p in txts]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--codes", help="逗号分隔股票代码；缺省=全部缓存报告")
    ap.add_argument("--sections", help="逗号分隔段名（缺省=选择器链点名的段）")
    ap.add_argument("--no-drop-junk", action="store_true",
                    help="不摘脚注句子条目（默认会摘：判据已收窄为「含。+长度>40+整行不可命中」，"
                         "只删定位不到的脚注行，不动任何切片边界）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    codes = [c.strip() for c in (args.codes or "").split(",") if c.strip()] or None
    sections = ([x.strip() for x in args.sections.split(",") if x.strip()]
                if args.sections else DEFAULT_SECTIONS)
    stems = _stems(codes)
    if not stems:
        raise SystemExit(f"没有缓存报告：{CACHE_DIR}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = OUT_DIR / f"outlines-{stamp}"
    total_fixed = 0
    print(f"报告 {len(stems)} 份；dry_run={args.dry_run}")
    for stem in stems:
        txt = Path(stem + ".txt")
        if not txt.exists():
            continue
        text = txt.read_text(encoding="utf-8", errors="replace")
        for kind in OUTLINE_KINDS:
            path = Path(stem + kind)
            if not path.exists():
                continue
            try:
                entries = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"  [skip] {path.name}: 解析失败 {exc}")
                continue
            if not isinstance(entries, list):
                continue
            before = [e.get("title") for e in entries]
            offsets = None
            po_path = Path(stem + ".page_offsets.json")
            if po_path.exists():
                try:
                    _po = json.loads(po_path.read_text(encoding="utf-8"))
                    offsets = _po if isinstance(_po, list) else _po.get("offsets")
                except Exception:
                    offsets = None
            entries, fixed = repair_entries(text, entries, sections, offsets)
            if not args.no_drop_junk:
                entries, junk = drop_junk_entries(text, entries)
                if junk:
                    print(f"  [drop] {path.name}: {junk} 条句子碎片条目（子串会抢选择器）")
                fixed += junk
            total_fixed += fixed
            if not fixed:
                continue
            print(f"  [fix] {path.name}: {fixed} 条标题改为正文写法")
            if args.dry_run:
                shown = 0
                for old, entry in zip(before, entries):
                    if old != entry.get("title") and shown < 3:
                        print(f"        {old!r} -> {entry['title']!r}")
                        shown += 1
                continue
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_dir / path.name)
            path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")

    print(f"\nfixed_titles={total_fixed} dry_run={args.dry_run}"
          + (f" backup={backup_dir}" if total_fixed and not args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
