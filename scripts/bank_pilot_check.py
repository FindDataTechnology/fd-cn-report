#!/usr/bin/env python
"""银行监管指标逐值核对（awaken-banking-report-ingest 3.2）。

做法：对指定股票+年份调 `indicators_client.extract_indicators` 抽 17 项监管指标，
**同时**从缓存的报告正文里截出每个指标的原文证据片段（±窗口），把「抽取值 / 原文证据」
并排写进 JSON 与 Markdown，供人工逐值判定。

为什么不自动判对错：`percent_value` 那次教训——错值和蒙对的值在返回值上无法区分，
只有对准原文才算验证。脚本只负责把原文摆到眼前，判定留痕在 `verdict` 字段（人工填）。

用法：
  python3 scripts/bank_pilot_check.py --codes 601398,600036 --year 2025
  python3 scripts/bank_pilot_check.py --codes 601288 --year 2024 --form 年度报告
输出：
  output/bank-pilot/check-<code>-<year>-<form>.json
  output/bank-pilot/check-<code>-<year>-<form>.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

OUT_DIR = _REPO / "output" / "bank-pilot"
CACHE_DIR = _REPO / ".cache" / "reports"

#: 17 项监管指标（spec 12 项 + 本轮补齐 3 项 + 迁徙率拆分 4 项）
INDICATORS = [
    "净息差", "净利差", "不良贷款率", "不良贷款余额", "拨备覆盖率", "拨贷比",
    "资本充足率", "核心一级资本充足率", "一级资本充足率", "流动性覆盖率",
    "成本收入比", "杠杆率", "净稳定资金比例",
    "正常类贷款迁徙率", "关注类贷款迁徙率", "次级类贷款迁徙率", "可疑类贷款迁徙率",
]

#: 各指标的原文标签（报告用词不一，列全再搜）
LABELS: dict[str, list[str]] = {
    "净息差": ["净息差", "净利息收益率"],
    "净利差": ["净利差", "净利息差"],
    "不良贷款率": ["不良贷款率"],
    "不良贷款余额": ["不良贷款3", "不良贷款余额", "不良贷款2", "不良贷款1", "不良贷款"],
    "拨备覆盖率": ["拨备覆盖率"],
    "拨贷比": ["拨贷比", "贷款拨备率"],
    "资本充足率": ["资本充足率"],
    "核心一级资本充足率": ["核心一级资本充足率"],
    "一级资本充足率": ["一级资本充足率"],
    "流动性覆盖率": ["流动性覆盖率"],
    "成本收入比": ["成本收入比"],
    "杠杆率": ["杠杆率"],
    "净稳定资金比例": ["净稳定资金比例"],
    "正常类贷款迁徙率": ["正常", "贷款迁徙率"],
    "关注类贷款迁徙率": ["关注"],
    "次级类贷款迁徙率": ["次级"],
    "可疑类贷款迁徙率": ["可疑"],
}

WINDOW = 110


def _report_text(stock_code: str, year: int, form: str) -> str | None:
    """取缓存正文；优先匹配 form，退而取同年任一份。"""
    pats = [f"{stock_code}_{year}_{form}_*.txt", f"{stock_code}_{year}_*.txt"]
    for pat in pats:
        hits = sorted(CACHE_DIR.glob(pat))
        if hits:
            return hits[0].read_text(encoding="utf-8", errors="replace")
    return None


def _evidence(text: str, indicator: str, limit: int = 3) -> list[str]:
    """截原文证据片段（去换行，最多 limit 条）。"""
    flat = re.sub(r"\s*\n\s*", " ⏎ ", text)
    out: list[str] = []
    for label in LABELS.get(indicator, [indicator]):
        for m in re.finditer(re.escape(label), flat):
            s = max(0, m.start() - 30)
            out.append(flat[s:m.end() + WINDOW])
            if len(out) >= limit:
                return out
    return out


def check_one(stock_code: str, year: int, form: str) -> dict:
    import indicators_client as IC

    bundle = IC.extract_indicators(stock_code, year, indicators=INDICATORS,
                                   form=form, extractor_mode="llm")
    text = _report_text(stock_code, year, form) or ""
    rows = []
    for ind in INDICATORS:
        v = (bundle.get("indicators") or {}).get(ind) or {}
        rows.append({
            "indicator": ind,
            "value": v.get("value"),
            "unit": v.get("unit"),
            "extractor": v.get("extractor"),
            "source": v.get("source"),
            "note": v.get("note"),
            "evidence": _evidence(text, ind),
            "verdict": "",  # 人工填 ok / wrong / undisclosed；留空=未核
        })
    return {
        "stock_code": stock_code,
        "company": bundle.get("company_name"),
        "year": year,
        "form": form,
        "pdf_url": bundle.get("pdf_url"),
        "missing": bundle.get("missing"),
        "unresolved": bundle.get("unresolved"),
        "rows": rows,
    }


def _markdown(doc: dict) -> str:
    lines = [f"# 监管指标逐值核对 {doc['stock_code']} {doc['company']} FY{doc['year']} {doc['form']}",
             "",
             f"- PDF: {doc.get('pdf_url')}",
             f"- missing: {doc.get('missing')}",
             "",
             "| 指标 | 抽取值 | 单位 | 提取器 | 原文证据 | 判定 |",
             "|---|---|---|---|---|---|"]
    for r in doc["rows"]:
        ev = (r["evidence"][0] if r["evidence"] else "（原文未找到标签）")
        ev = ev.replace("|", "／")
        lines.append(f"| {r['indicator']} | {r['value']} | {r['unit']} | {r['extractor']} "
                     f"| {ev} | {r['verdict']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--codes", required=True, help="逗号分隔股票代码")
    ap.add_argument("--year", type=int, required=True, help="会计年度")
    ap.add_argument("--form", default="年度报告")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    summary = []
    for code in codes:
        try:
            doc = check_one(code, args.year, args.form)
        except Exception as exc:  # 网关 503 等：一家失败不拖垮整批
            print(f"{code}: 抽取失败 -> {type(exc).__name__}: {exc}")
            summary.append((code, "(失败)", 0, len(INDICATORS)))
            continue
        stem = f"check-{code}-{args.year}-{args.form}"
        (OUT_DIR / f"{stem}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (OUT_DIR / f"{stem}.md").write_text(_markdown(doc), encoding="utf-8")
        filled = sum(1 for r in doc["rows"] if r["value"] is not None)
        summary.append((code, doc.get("company"), filled, len(doc["rows"])))
        print(f"{code} {doc.get('company')}: 有值 {filled}/{len(doc['rows'])} -> {stem}.md")

    print("\n汇总：")
    for code, name, filled, total in summary:
        print(f"  {code} {name}: {filled}/{total}")
    print(f"\n核对记录目录：{OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
