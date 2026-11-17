#!/usr/bin/env python3
"""财务面板 —— 把 fd-cn-report 的三大报表渲染成一份可点回公告的 HTML。

用法::

    python3 scripts/panel.py 600519 2023              # 写 out/panel-600519-2023.html
    python3 scripts/panel.py 600519 2023 --open       # 顺便用浏览器打开
    python3 scripts/panel.py 600519 2023 600965 2024  # 多家公司

这不是理杏仁。**只做一件事**：把「我们有能力取、但从来没有一个人能看见」的
数字，连同它们的公告来源，摆到一个页面上。每个数字旁边都能看到它来自哪份公告、
第几页、原文长什么样。

ponytail: 单文件 HTML + 内联 CSS，无框架无构建。够用就停。
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

STATEMENT_LABELS = {
    "income_statement": "利润表",
    "balance_sheet": "资产负债表",
    "cashflow": "现金流量表",
}

CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; font: 15px/1.6 -apple-system, "PingFang SC", sans-serif;
       max-width: 1100px; margin-inline: auto; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 32px 0 8px; border-bottom: 1px solid #8884; padding-bottom: 6px; }
.meta { color: #666; font-size: 13px; margin-bottom: 16px; }
.meta a { color: inherit; }
.src { display: inline-block; font: 12px/1.4 ui-monospace, monospace;
       background: #8881; border-radius: 4px; padding: 1px 6px; margin-left: 6px; }
.missing { color: #b45309; background: #fef3c7; padding: 8px 12px; border-radius: 6px; }
pre { white-space: pre-wrap; word-break: break-word; background: #8881; padding: 12px;
      border-radius: 6px; font: 12px/1.6 ui-monospace, monospace; max-height: 420px; overflow: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; margin: 8px 0; }
th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid #8883; vertical-align: top; }
th { font-weight: 600; color: #555; font-size: 12px; }
td.num { font-family: ui-monospace, monospace; text-align: right; white-space: nowrap; }
td.note { color: #888; width: 48px; }
tr:hover td { background: #8881; }
details.raw { margin-top: 8px; }
details.raw summary { font-weight: 400; font-size: 12px; color: #666; }
details { margin: 8px 0; }
summary { cursor: pointer; font-weight: 600; }
nav a { margin-right: 12px; font-size: 13px; }
"""


def parse_rows(text: str) -> list[dict]:
    """把「一格一行」的抽取文本还原成行：标签 + 附注 + 数值。

    巨潮 PDF 抽出来是每格一行，不是表格。这里只做一种最小分组：非数字行开新行，
    数字行追加为值；纯数字且不超过 3 位的短行视作附注号。

    这是**展示层启发式**，判错的代价只是这行没排好——原始文本始终留在下方
    <pre> 里可对照，不会丢数据。ponytail: 不做表格坐标解析。
    """
    num = re.compile(r"^-?[\d,]+\.\d{2}$")
    rows: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        tokens = line.split()
        if tokens and all(num.match(v) for v in tokens):
            if rows:
                rows[-1]["values"].extend(tokens)
            continue
        if line.isdigit() and len(line) <= 3 and rows and not rows[-1]["values"]:
            rows[-1]["note"] = line
            continue
        rows.append({"label": line, "note": "", "values": []})
    return rows


def render_rows(text: str) -> str:
    """行表：标签 / 附注 / 本期 / 上期。原始文本另存，判错只影响排版不影响数据。"""
    all_rows = [r for r in parse_rows(text) if r["label"]]
    if len(all_rows) < 3:
        return f"<pre>{html.escape(text)}</pre>"  # 型不成表就退还原样

    # PDF 表头（表名、单位、「项目/附注/2023年度/2022年度」）是表格之前的一段，
    # 第一个带数值的行为界。表头里的年份做列名，表头本身不重复成数据行。
    first_data = next((i for i, r in enumerate(all_rows) if r["values"]), 0)
    preamble, rows = all_rows[:first_data], all_rows[first_data:]
    years = [r["label"] for r in preamble if re.fullmatch(r"20\d{2}\s*年度", r["label"].strip())]
    c1, c2 = (years[0], years[1]) if len(years) >= 2 else ("本期", "上期")

    out = [f"<table><thead><tr><th>项目</th><th>附注</th>"
           f"<th class='num'>{html.escape(c1)}</th>"
           f"<th class='num'>{html.escape(c2)}</th></tr></thead><tbody>"]
    for r in rows:
        vals = r["values"] + ["", ""]
        cls = " class='num'" if r["values"] else ""
        out.append(
            f"<tr><td>{html.escape(r['label'])}</td>"
            f"<td class='note'>{html.escape(r['note'])}</td>"
            f"<td{cls}>{html.escape(vals[0])}</td>"
            f"<td{cls}>{html.escape(vals[1])}</td></tr>"
        )
    out.append("</tbody></table>")
    return "".join(out)


def build(filings: list[dict]) -> str:
    parts = [
        "<!doctype html><meta charset='utf-8'>",
        "<title>财务面板 · fd-cn-report</title>",
        f"<style>{CSS}</style>",
        "<h1>财务面板</h1>",
        "<p class='meta'>数据来自巨潮官方披露，逐表可点回公告原文。"
        "本面板只呈现 <code>get_financial_statements</code> 已经取到的内容，"
        "不补数、不插值、不推测。</p>",
    ]
    toc = [
        f"<a href='#c{i}'>{html.escape(f['company_name'])} {f['year']}</a>"
        for i, f in enumerate(filings) if "error" not in f
    ]
    if toc:
        parts.append("<nav>" + "".join(toc) + "</nav>")

    for i, f in enumerate(filings):
        if "error" in f:
            parts.append(f"<p class='missing'>取数失败：{html.escape(str(f['error']))}</p>")
            continue
        title = f"{html.escape(f['company_name'])}（{f['stock_code']}）· {f['year']} {html.escape(f['form'])}"
        aid = f.get("announcement_id") or ""
        atitle = f.get("announcement_title") or ""
        src = ""
        if aid:
            src = (f"<span class='src'>{html.escape(aid)}</span>"
                   f"<span class='src'>{html.escape(atitle)}</span>")
        parts.append(f"<h2 id='c{i}'>{title}{src}</h2>")
        if f.get("published"):
            parts.append(f"<p class='meta'>公告发布日 {html.escape(f['published'])} · "
                         f"<a href='{html.escape(f['pdf_url'])}' target='_blank'>原文 PDF</a></p>")
        if f.get("missing"):
            parts.append("<p class='missing'>未定位到的报表："
                         + "、".join(STATEMENT_LABELS.get(k, k) for k in f["missing"])
                         + "</p>")
        for key, label in STATEMENT_LABELS.items():
            st = (f.get("statements") or {}).get(key)
            if not st:
                continue
            page = (st.get("outline_entry") or {}).get("page")
            # Every number below sits on this page of this announcement — that is
            # the whole point of the panel: page-level provenance, visible.
            anchor = (f"<span class='src'>第 {page} 页</span>" if page else "")
            body = render_rows(st.get("text") or "")
            raw = html.escape(st.get("text") or "")
            parts.append(
                f"<details><summary>{label}{anchor}</summary>"
                f"{body}"
                f"<details class='raw'><summary>原始抽取文本</summary><pre>{raw}</pre></details>"
                f"</details>"
            )
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a filing-traceable financial panel.")
    ap.add_argument("pairs", nargs="+", help="ticker year [ticker year ...]")
    ap.add_argument("--out", default="out")
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()

    if len(args.pairs) % 2:
        print("pairs must be ticker/year couples", file=sys.stderr)
        return 2
    import cnreport_tools as t  # after sys.path setup

    filings = []
    for ticker, year in zip(args.pairs[::2], args.pairs[1::2]):
        filings.append(t.get_financial_statements(ticker, int(year)))

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    name = "-".join(f"{f.get('stock_code', p)}" for p, f in zip(args.pairs[::2], filings))
    path = outdir / f"panel-{name}.html"
    path.write_text(build(filings), encoding="utf-8")

    ok = sum(1 for f in filings if "error" not in f)
    print(f"{ok}/{len(filings)} 家公司取数成功 -> {path}")
    for f in filings:
        if "error" in f:
            print(f"  FAIL {f.get('error')}", file=sys.stderr)
        elif f.get("missing"):
            print(f"  PART {f['stock_code']} 缺 {f['missing']}", file=sys.stderr)
    if args.open:
        webbrowser.open(path.resolve().as_uri())
    return 0 if ok == len(filings) else 1


if __name__ == "__main__":
    sys.exit(main())
