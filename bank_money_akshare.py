"""金额类银行指标的 akshare 结构化取数（主源）。

**为什么 akshare 是主源、GTA 只做交叉校验**：同一批科目两处都有，但
akshare（东财报表接口）**没有时滞**——实测工行已到 2026-09-30 季报，而 GTA 面板
滞后一个财年（FY2025 全空）。两源单位同为元、口径同为**资产负债表账面值（含应计
利息）**，故在重叠期应当逐值相等；不相等说明其中一侧出了问题。

本模块只做数据变换，不联网也不写库：

- ``code_to_symbol``    六位代码 → 东财符号（``601398`` → ``SH601398``）
- ``periods_from_sheets`` 资产负债表 + 利润表 → ``{indicator_zh, firm_id, year, value}``
- ``cross_check``       与 GTA 取数结果逐值比对（重叠期必须完全相等）

**年报口径**：只取 12-31 期末（与概念 ``frequency=yearly`` 一致）。季报数据在
akshare 里是有的，但把季频写进 yearly 概念会重演「granularity 退化」的老坑，
故本期只登记年报，季度留待单独裁定。
"""
from __future__ import annotations

import json
from pathlib import Path

_REPO = Path(__file__).resolve().parent
SOURCES = _REPO / "docs" / "bank-money-indicator-sources.json"

STATEMENT_OF = {"balance": "balance", "profit": "profit"}
ANNUAL_SUFFIX = "12-31"


def load_sources(path: str | Path | None = None) -> dict:
    p = Path(path) if path else SOURCES
    data = json.loads(p.read_text(encoding="utf-8"))
    for it in data["indicators"]:
        if not it.get("akshare", {}).get("column"):
            raise ValueError(f"{it['indicator_zh']} 缺口 akshare 列映射")
    return data


def code_to_symbol(code: str, exchange: str | None = None) -> str:
    """六位代码 → 东财符号。600/601/603/605/688 → SH，000/001/002/003/300 → SZ。"""
    c = str(code).strip().zfill(6)
    if exchange:
        return f"{exchange.upper()}{c}"
    if c[0] in "69":
        return f"SH{c}"
    if c[0] in "023":
        return f"SZ{c}"
    if c[0] in "48":
        return f"BJ{c}"
    raise ValueError(f"无法判定交易所: {code}")


def _rows_by_period(df) -> dict[str, dict]:
    """DataFrame → {REPORT_DATE(YYYY-MM-DD): {列: 值}}。"""
    out: dict[str, dict] = {}
    if df is None or len(df) == 0:
        return out
    date_col = "REPORT_DATE"
    if date_col not in df.columns:
        return out
    for _, row in df.iterrows():
        raw = row.get(date_col)
        if raw is None:
            continue
        day = str(raw)[:10]
        out[day] = {k: row.get(k) for k in df.columns}
    return out


def periods_from_sheets(sheets: dict, firm_id: str, sources: dict,
                        years: list[int] | None = None) -> tuple[list[dict], list[dict]]:
    """把一只股票的报表帧转成面板行（元）。

    ``sheets``：``{"balance": df, "profit": df}``。
    返回 ``(行, 留痕)``；留痕按 (指标, 期末) 记缺失原因，便于排查列名漂移。
    """
    by_period = {name: _rows_by_period(df) for name, df in sheets.items()}
    rows: list[dict] = []
    trace: list[dict] = []
    for it in sources["indicators"]:
        spec = it["akshare"]
        stmt = spec["statement"]
        col = spec["column"]
        if stmt not in by_period:
            trace.append({"indicator_zh": it["indicator_zh"], "reason": "statement-missing",
                          "statement": stmt})
            continue
        for day, cells in sorted(by_period[stmt].items()):
            if not day.endswith(ANNUAL_SUFFIX):
                continue
            year = int(day[:4])
            if years and year not in years:
                continue
            val = cells.get(col)
            if val is None or val != val:  # None 或 NaN
                trace.append({"indicator_zh": it["indicator_zh"], "reason": "value-missing",
                              "period": day, "column": col})
                continue
            rows.append({"indicator_zh": it["indicator_zh"], "firm_id": str(firm_id).zfill(6),
                         "year": year, "value": float(val), "period": day})
    return rows, trace


def cross_check(ak_rows: list[dict], gta_values: list[dict]) -> dict:
    """akshare 行 vs GTA 面板值逐点比对（重叠期必须完全相等）。

    ``gta_values`` 形如 ``[{indicator_zh, firm_id, year, value}]``（元）。
    返回 ``{compared, mismatched[], only_akshare[], only_gta[]}``；
    ``mismatched`` 非空即视为源缺陷（口径或列映射漂移）。
    """
    def key(r):
        return (r["indicator_zh"], str(r["firm_id"]).zfill(6), int(r["year"]))

    ak = {key(r): float(r["value"]) for r in ak_rows}
    gt: dict[tuple, float] = {}
    uncomparable: set[tuple] = set()
    for r in gta_values:
        k = key(r)
        v = r.get("value")
        if isinstance(v, (int, float)):
            gt[k] = float(v)
        else:
            # 非数值（None / "—"）不能静默丢掉：它既不是「无值」之外的空，也
            # 可能是一条该被看见的坏数据。单列计数并保留在 only_gta 侧。
            uncomparable.add(k)
    common = set(ak) & set(gt)
    mismatched = [{"indicator_zh": k[0], "firm_id": k[1], "year": k[2],
                   "akshare": ak[k], "gta": gt[k]}
                  for k in sorted(common) if abs(ak[k] - gt[k]) > 0.5]
    return {
        "compared": len(common),
        "mismatched": mismatched,
        "uncomparable_gta": [{"indicator_zh": k[0], "firm_id": k[1], "year": k[2]}
                             for k in sorted(uncomparable - set(ak))],
        "only_akshare": [{"indicator_zh": k[0], "firm_id": k[1], "year": k[2]}
                         for k in sorted(set(ak) - set(gt) - uncomparable)],
        "only_gta": [{"indicator_zh": k[0], "firm_id": k[1], "year": k[2]}
                     for k in sorted(set(gt) - set(ak))],
    }
