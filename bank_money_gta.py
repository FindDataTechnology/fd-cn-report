"""金额类银行指标的结构化取数（bank-indicator-money-unit-support）。

**为什么不在报告正文里解析单位**：四种文本启发式（design.md 决策 1 的 A–D）在 10 个
样本上只做到 3–5 个正确、3–4 个判成「元」，加阈值就是过拟合。改走 windows-admin 的
GTA 上市公司面板：值统一以**元**存储，单位歧义从源头消失。

本模块只做三件事，不联网、不写库：

1. 读口径表 ``docs/bank-money-indicator-sources.json`` —— 指标 → 面板变量 + 口径钉死 +
   「无结构化源覆盖」清单；
2. 把面板行（元）转成待登记的观测行，携带 ``source_used='gta-panel'`` 与口径说明；
3. 用 ``docs/golden-bank-money-gta.json``（证据取自年报原文）逐值核验。

**纪律**：面板滞后一个财年（FY2025 全空）⇒ 无值的年份记「源未入库」，
SHALL NOT 用上一年值顶替，也 SHALL NOT 插值。
"""
from __future__ import annotations

import json
from pathlib import Path

_REPO = Path(__file__).resolve().parent
SOURCES = _REPO / "docs" / "bank-money-indicator-sources.json"
GOLDEN = _REPO / "docs" / "golden-bank-money-gta.json"

SOURCE_USED = "gta-panel"
ENTITY_TYPE = "stock"
YUAN_PER_MILLION = 1_000_000.0

#: 报告类型 → 期末日（金额类指标只在年报口径登记）
PERIOD_END = {"year": "12-31"}


def load_sources(path: str | Path | None = None) -> dict:
    """读口径表。缺 indicators / unavailable 视为口径表损坏，直接抛错。"""
    p = Path(path) if path else SOURCES
    data = json.loads(p.read_text(encoding="utf-8"))
    for key in ("source", "indicators", "unavailable"):
        if key not in data:
            raise ValueError(f"口径表缺 {key}: {p}")
    return data


def load_golden(path: str | Path | None = None) -> dict:
    p = Path(path) if path else GOLDEN
    return json.loads(p.read_text(encoding="utf-8"))


def variables(sources: dict) -> list[str]:
    """口径表里需要从面板取的全部变量名（去重保序）。"""
    out: list[str] = []
    for it in sources["indicators"]:
        if it["gta_name"] not in out:
            out.append(it["gta_name"])
    return out


def unavailable_reasons(sources: dict) -> dict[str, str]:
    """指标 → 不可得原因。盘点输出直接用它，避免每次重编理由。"""
    return {it["indicator_zh"]: it["reason"] for it in sources["unavailable"]}


def to_millions(value_yuan: float) -> float:
    """元 → 百万元，只用于人工复核与日志；登记按元存（concept.unit=currency）。"""
    return value_yuan / YUAN_PER_MILLION


def to_observations(values: list[dict], sources: dict,
                    years: list[int] | None = None) -> tuple[list[dict], dict]:
    """面板行 → 观测行。

    ``values`` 每项 ``{indicator_zh, firm_id, year, value}``，``value`` 单位是元。
    返回 ``(观测行, 留痕)``；留痕分四类：
      · ``empty``  —— 口径表里有该指标，但面板一行都没有
      · ``empty_years`` —— 给了 ``years`` 时，某指标整年无值（面板滞后/未入库）
      · ``unmapped`` —— 面板给了口径表外的指标名
      · ``bad``  —— 值非数值或缺 firm/year

    ``empty_years`` 是滞后信号的机器可读形态：只有整年一行为空才记，避免把
    「个别银行某年未披露」误当成源不可用。
    """
    by_ind = {it["indicator_zh"]: it for it in sources["indicators"]}
    rows: list[dict] = []
    trace: dict[str, list] = {"empty": [], "empty_years": [], "unmapped": [], "bad": []}
    seen: set[tuple[str, str, int]] = set()

    for v in values:
        ind = v.get("indicator_zh")
        meta = by_ind.get(ind)
        if meta is None:
            trace["unmapped"].append(ind)
            continue
        firm = str(v.get("firm_id") or "").strip()
        year = v.get("year")
        val = v.get("value")
        if not firm or not isinstance(year, int) or not isinstance(val, (int, float)):
            trace["bad"].append({"indicator_zh": ind, "value": v})
            continue
        key = (ind, firm.zfill(6), year)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "indicator_zh": ind,
            "concept": meta["concept"],
            "entity_type": ENTITY_TYPE,
            "entity_code": firm.zfill(6),
            "year": year,
            "date": f"{year}-{PERIOD_END['year']}",
            "granularity": "year",
            "value": val,
            "unit": meta["unit"],
            "source_used": SOURCE_USED,
            "caliber": meta["caliber"],
        })

    for it in sources["indicators"]:
        if not any(r["indicator_zh"] == it["indicator_zh"] for r in rows):
            trace["empty"].append(it["indicator_zh"])
            continue
        for y in (years or []):
            if not any(r["indicator_zh"] == it["indicator_zh"] and r["year"] == y
                       for r in rows):
                trace["empty_years"].append({"indicator_zh": it["indicator_zh"],
                                             "year": y, "reason": "source_empty"})
    rows.sort(key=lambda r: (r["indicator_zh"], r["entity_code"], r["year"]))
    return rows, trace


def verify_anchors(values: list[dict], golden: dict) -> dict:
    """把面板值与年报原文锚逐值比对。

    返回 ``{"checked", "mismatched", "missing"}``；``mismatched`` 与 ``missing``
    非空即视为失败（调用方据此非零退出）。锚的证据来自年报原文，不来自面板，
    因此这是**独立**核验而不是自证。数值按元精确比较。
    """
    idx = {(v["indicator_zh"], str(v["firm_id"]).zfill(6), v["year"]): v["value"]
           for v in values if isinstance(v.get("value"), (int, float))}
    mismatched: list[dict] = []
    missing: list[dict] = []
    checked = 0
    for a in golden["anchors"]:
        key = (a["indicator_zh"], str(a["firm_id"]).zfill(6), a["year"])
        got = idx.get(key)
        if got is None:
            missing.append({"indicator_zh": key[0], "firm_id": key[1], "year": key[2],
                            "expected": a["value"], "evidence": a["evidence"]})
            continue
        checked += 1
        if abs(float(got) - float(a["value"])) > 0.5:
            mismatched.append({"indicator_zh": key[0], "firm_id": key[1], "year": key[2],
                               "expected": a["value"], "got": got,
                               "evidence": a["evidence"]})
    return {"checked": checked, "mismatched": mismatched, "missing": missing}


def lag_note(sources: dict, years: list[int], values: list[dict]) -> dict:
    """按年统计每个指标的非空家数 —— 用来把「面板滞后」变成可复核的数字。"""
    out: dict[str, dict[int, int]] = {}
    for it in sources["indicators"]:
        ind = it["indicator_zh"]
        per_year: dict[int, int] = {}
        for y in years:
            per_year[y] = sum(1 for v in values
                              if v.get("indicator_zh") == ind and v.get("year") == y
                              and isinstance(v.get("value"), (int, float)))
        out[ind] = per_year
    return out
