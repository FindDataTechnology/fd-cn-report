"""银行监管比率的结构化取数：东财 F10 主要指标（主源）。

**为什么需要它**：阈值告警原先只覆盖 5/42 家——比率只来自 `cn-report` 的报告抽取，
而报告抽取只有 5 家试点。实测东财 F10 原始接口
``RPT_F10_FINANCE_MAINFINADATA`` 直接带银行监管比率，覆盖全部 A 股银行，且无滞后
（工行已到 2026-09-30 季报）。akshare 没有封装这条数据，所以这里直连 datacenter API。

**字段口径已逐值对齐**（不是猜的）：拿 harden 期从报告原文核过的 golden 锚
（5 家 × 4 项 = 20 个点）去对 FY2025，**20/20 完全一致**：

    NEWCAPITALADER        → 资本充足率        601398 18.76 ✓
    FIRST_ADEQUACY_RATIO  → 一级资本充足率    601398 14.94 ✓
    BLDKBBL               → 拨备覆盖率        601398 213.60 ✓
    LOAN_PROVISION_RATIO  → 贷款拨备率(拨贷比) 601398 2.79 ✓

**明确不用的字段**（口径对不上就不能用）：

    LIQUIDATION_RATIO     → 601398 = 108.03，而 golden 流动性比例 = 63.20 ⇒ **不是该指标**
                            （量级更像流动性匹配率，但接口不给中文名，故不猜、不映射）
    RCAPITAL_RATIO / CAPITAL_LEVERAGE_RATIO / LIQUIDITY_COVERAGE_RATIO
                          → 该来源对本批银行恒为 null ⇒ 无值可用

所以本模块只出 4 个指标；核心一级 / 杠杆率 / LCR / NSFR 仍需报告抽取路径。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

SOURCE_USED = "eastmoney-f10"
REPORT_NAME = "RPT_F10_FINANCE_MAINFINADATA"
BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"

#: 指标中文名（= daas.db llm_rules.indicator 同名）→ (F10 字段, 概念码, 单位)
FIELDS: dict[str, tuple[str, str, str]] = {
    "资本充足率": ("NEWCAPITALADER", "financials.capital_adequacy_ratio", "%"),
    "一级资本充足率": ("FIRST_ADEQUACY_RATIO", "financials.tier1_capital_adequacy_ratio", "%"),
    "拨备覆盖率": ("BLDKBBL", "financials.provision_coverage_ratio", "%"),
    "贷款拨备率": ("LOAN_PROVISION_RATIO", "financials.loan_loss_provision_ratio", "%"),
}

#: 已知不能用/无值的字段，留档防止后人再试一遍。
REJECTED = {
    "LIQUIDATION_RATIO": "601398 实测 108.03，与 golden 流动性比例 63.20 不符，不是该指标",
    "RCAPITAL_RATIO": "全量复核：42 家银行 0/42 有值（不是抽样）",
    "CAPITAL_LEVERAGE_RATIO": "全量复核：42 家银行 0/42 有值",
    "LIQUIDITY_COVERAGE_RATIO": "全量复核：42 家银行 0/42 有值",
}
#: 全量复核记录（2026-11-08）：不要再用抽样结论判断「有没有值」。
#: 第一次扫用了 `select distinct stock_code from report_documents`（143 家，混入
#: 其他业务线的非银行主体），得到「核心一级 84 家非空」——**假阳性**：84 > 42 且
#: 样例是 000019/000048/000505 这类消费品股。按真银行宇宙（42 家）重扫，
#: 核心一级 / 杠杆率 / LCR **均为 0/42**；拨贷比 42/42（但该规则因区间判据停用）。
COVERAGE_AUDIT = {
    "NEWCAPITALADER": "42/42", "FIRST_ADEQUACY_RATIO": "42/42",
    "BLDKBBL": "42/42", "LOAN_PROVISION_RATIO": "42/42",
    "RCAPITAL_RATIO": "0/42", "CAPITAL_LEVERAGE_RATIO": "0/42",
    "LIQUIDITY_COVERAGE_RATIO": "0/42",
}

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}

#: 报告期 → 是否年报（granularity 用）
ANNUAL_SUFFIX = "12-31"


def _get_json(url: str, timeout: int = 25) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def fetch_rows(code: str, pages: int = 3, page_size: int = 20) -> list[dict]:
    """取一只股票的主要指标行（按报告期倒序）。

    过滤键必须是 ``SECURITY_CODE``：用 ``SECUCODE``（带 .SH 后缀那种）实测返回 0 行。
    """
    out: list[dict] = []
    for page in range(1, pages + 1):
        url = BASE + "?" + urllib.parse.urlencode({
            "reportName": REPORT_NAME, "columns": "ALL",
            "pageSize": page_size, "pageNumber": page,
            "filter": f'(SECURITY_CODE="{code}")',
            "sortColumns": "REPORT_DATE", "sortTypes": -1,
        })
        data = _get_json(url)
        rows = (data.get("result") or {}).get("data") or []
        out.extend(rows)
        if len(rows) < page_size:
            break
    return out


def to_values(rows: list[dict], firm_id: str, years: list[int] | None = None
              ) -> tuple[list[dict], list[dict]]:
    """F10 行 → 观测输入行 ``{indicator_zh, firm_id, year, value, period}``。

    只保留年报口径（12-31）：概念 ``frequency=yearly``，把季频塞进去会重演
    「granularity 退化」的老坑。返回 ``(行, 留痕)``。
    """
    values: list[dict] = []
    trace: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for row in rows:
        period = str(row.get("REPORT_DATE") or "")[:10]
        if not period.endswith(ANNUAL_SUFFIX):
            continue
        year = int(period[:4])
        if years and year not in years:
            continue
        for ind, (col, _concept, _unit) in FIELDS.items():
            key = (ind, year)
            if key in seen:
                continue
            raw = row.get(col)
            if raw is None:
                trace.append({"indicator_zh": ind, "firm_id": firm_id,
                              "period": period, "reason": "value-missing", "column": col})
                continue
            try:
                val = float(raw)
            except (TypeError, ValueError):
                trace.append({"indicator_zh": ind, "firm_id": firm_id,
                              "period": period, "reason": "not-numeric", "column": col})
                continue
            seen.add(key)
            values.append({"indicator_zh": ind, "firm_id": str(firm_id).zfill(6),
                           "year": year, "value": val, "period": period})
    return values, trace


def verify_golden(values: list[dict], golden: dict) -> dict:
    """与 golden 锚逐值核对（锚来自报告原文，是独立证据）。

    返回 ``{checked, mismatched, missing}``；后两者非空即视为不可登记。
    """
    idx = {(v["indicator_zh"], str(v["firm_id"]).zfill(6), int(v["year"])): v["value"]
           for v in values}
    mismatched: list[dict] = []
    missing: list[dict] = []
    checked = 0
    for ind, anchors in (golden.get("indicators") or {}).items():
        if ind not in FIELDS:
            continue
        for a in anchors:
            key = (ind, str(a["entity_code"]).zfill(6), int(a["fiscal_year"]))
            got = idx.get(key)
            if got is None:
                missing.append({"indicator_zh": key[0], "firm_id": key[1], "year": key[2],
                                "expected": a["value"]})
                continue
            checked += 1
            if abs(float(got) - float(a["value"])) > 0.005:
                mismatched.append({"indicator_zh": key[0], "firm_id": key[1],
                                   "year": key[2], "expected": a["value"], "got": got})
    return {"checked": checked, "mismatched": mismatched, "missing": missing}
