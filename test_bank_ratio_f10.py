"""东财 F10 银行监管比率取数的离线单测（不联网）。

字段口径的实弹证据见模块 docstring：harden 期 golden 锚 5 家×4 项 20/20 一致。
"""
from __future__ import annotations

import bank_ratio_f10 as F10


# --- 字段白名单 ---------------------------------------------------------------

def test_only_verified_fields_are_mapped():
    """映射表里只能是拿 golden 逐值核过的字段。"""
    cols = {v[0] for v in F10.FIELDS.values()}
    assert cols == {"NEWCAPITALADER", "FIRST_ADEQUACY_RATIO", "BLDKBBL",
                    "LOAN_PROVISION_RATIO"}


def test_rejected_fields_are_backed_by_a_full_universe_check():
    """拒绝理由必须是**全量复核**的结果，不是抽样。

    踩过：第一次拿 `report_documents` 的 143 家（混了消费品股）扫，
    得到「核心一级 84 家非空」；84 > 42 这个数字本身就是假阳性的证据。
    真银行宇宙重扫是 0/42。
    """
    for col, why in F10.REJECTED.items():
        if col == "LIQUIDATION_RATIO":
            continue  # 这条是口径不符，不是"无值"
        assert "0/42" in why, f"{col} 的拒绝理由必须写明全量结论"


def test_coverage_audit_covers_every_field():
    """每个已知字段都要在覆盖台账里留数，后人不必再扫一遍。"""
    for col in list(F10.FIELDS) and [v[0] for v in F10.FIELDS.values()]:
        assert col in F10.COVERAGE_AUDIT, col


def test_liquidation_ratio_is_not_mapped():
    """LIQUIDATION_RATIO 实测 108 而流动性比例 golden 是 63.2——绝不能映射。

    这是本轮最容易犯的错：字段名像「流动性」就拿来当流动性比例，量级差了 70%。
    """
    mapped = {v[0] for v in F10.FIELDS.values()}
    assert "LIQUIDATION_RATIO" not in mapped
    assert "LIQUIDATION_RATIO" in F10.REJECTED


def test_indicator_names_match_rule_database():
    """指标名要与 daas.db 的 llm_rules.indicator 同名（联结键）。"""
    assert set(F10.FIELDS) == {"资本充足率", "一级资本充足率", "拨备覆盖率", "贷款拨备率"}


# --- 行 → 观测输入 -----------------------------------------------------------

def _row(period, **cols):
    return {"REPORT_DATE": period, **cols}


def test_only_annual_periods_kept():
    rows = [_row("2025-09-30", NEWCAPITALADER=19.0),
            _row("2025-12-31", NEWCAPITALADER=18.76),
            _row("2026-06-30", NEWCAPITALADER=18.57)]
    vals, _ = F10.to_values(rows, "601398", years=[2025])
    assert [v["year"] for v in vals] == [2025]
    assert vals[0]["value"] == 18.76


def test_missing_value_is_traced():
    rows = [_row("2025-12-31", NEWCAPITALADER=18.76)]
    vals, trace = F10.to_values(rows, "601398", years=[2025])
    assert [v["indicator_zh"] for v in vals] == ["资本充足率"]
    assert {t["reason"] for t in trace} == {"value-missing"}


def test_non_numeric_value_is_traced_not_coerced():
    rows = [_row("2025-12-31", NEWCAPITALADER="—")]
    vals, trace = F10.to_values(rows, "601398", years=[2025])
    assert vals == [] and trace[0]["reason"] == "not-numeric"


def test_duplicate_period_keeps_first():
    rows = [_row("2025-12-31", NEWCAPITALADER=18.76),
            _row("2025-12-31", NEWCAPITALADER=99.99)]
    vals, _ = F10.to_values(rows, "601398", years=[2025])
    assert len([v for v in vals if v["indicator_zh"] == "资本充足率"]) == 1
    assert vals[0]["value"] == 18.76


def test_firm_code_is_zero_padded():
    rows = [_row("2025-12-31", NEWCAPITALADER=13.77)]
    vals, _ = F10.to_values(rows, "1", years=[2025])
    assert vals[0]["firm_id"] == "000001"


# --- 核锚 ---------------------------------------------------------------------

def _golden(**by_code):
    return {"indicators": {
        "资本充足率": [{"entity_code": c, "fiscal_year": 2025, "value": v}
                       for c, v in by_code.items()]}}


def test_verify_golden_all_match():
    vals = [{"indicator_zh": "资本充足率", "firm_id": "601398", "year": 2025, "value": 18.76}]
    res = F10.verify_golden(vals, _golden(**{"601398": 18.76}))
    assert res["checked"] == 1 and res["mismatched"] == [] and res["missing"] == []


def test_verify_golden_detects_mismatch():
    vals = [{"indicator_zh": "资本充足率", "firm_id": "601398", "year": 2025, "value": 18.5}]
    res = F10.verify_golden(vals, _golden(**{"601398": 18.76}))
    assert len(res["mismatched"]) == 1


def test_verify_golden_reports_missing():
    res = F10.verify_golden([], _golden(**{"601398": 18.76}))
    assert res["checked"] == 0 and len(res["missing"]) == 1


def test_verify_golden_ignores_non_f10_indicators():
    """golden 里 19 项指标，本模块只出 4 项，其余不该算 missing。"""
    golden = {"indicators": {"净息差": [{"entity_code": "601398", "fiscal_year": 2025,
                                        "value": 1.28}]}}
    res = F10.verify_golden([], golden)
    assert res["missing"] == []
