"""金额类银行指标结构化取数的离线单测（bank-indicator-money-unit-support）。

不联网：GTA 面板值一律用造出来的行，验的是口径承载、留痕分类、核锚三件事。
真值核验（对 windows-admin 的实弹）走
``scripts/register_bank_money_from_gta.py --verify``。
"""
import json
from pathlib import Path

import pytest

import bank_money_gta as bmg

_REPO = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def sources():
    return bmg.load_sources()


@pytest.fixture(scope="module")
def golden():
    return bmg.load_golden()


# --- 口径表完整性 -------------------------------------------------------------

def test_every_available_indicator_pins_caliber_with_evidence(sources):
    """口径表是唯一真源：每项都必须写清口径，且带年报原文证据。

    没有 ``caliber_evidence`` 的条目等于「口径靠猜」，而本变更的全部教训就是别猜。
    """
    for it in sources["indicators"]:
        for key in ("indicator_zh", "gta_name", "caliber", "caliber_evidence",
                    "concept", "unit"):
            assert it.get(key), f"{it.get('indicator_zh')} 缺 {key}"
        assert it["unit"] == "currency", "金额类指标单位一律 currency（元）"


def test_unavailable_list_does_not_overlap_available(sources):
    """同一指标不能既「有源」又「无源」——那会让启用判定自相矛盾。"""
    avail = {it["indicator_zh"] for it in sources["indicators"]}
    unavail = {it["indicator_zh"] for it in sources["unavailable"]}
    assert avail & unavail == set()
    assert len(unavail) == len(sources["unavailable"]), "无覆盖清单有重复项"


def test_unavailable_variants_boilerplate_is_kept_off(sources):
    """「无覆盖」清单里的贷款总额理由必须点明是净额/总额之别，防止被当近似可用。"""
    reason = bmg.unavailable_reasons(sources)["贷款和垫款总额"]
    assert "净额" in reason and "总额" in reason


def test_indicator_names_are_canonical_keys(sources):
    """指标名是联结键：必须与 daas.db 的 llm_rules.indicator 同名。

    实测踩点：面板标签是「利息净收入」、规则库是「净利息收入」，
    按名 join 会把这一项静默丢掉。故别名只能放 aliases，不能当键。
    """
    for it in sources["indicators"]:
        assert it["indicator_zh"] not in (it.get("aliases") or []), \
            f"{it['indicator_zh']} 把自己的规范名列进了别名"


def test_aliases_are_disjoint_and_resolve_to_canonical(sources):
    canonical = {it["indicator_zh"] for it in sources["indicators"]}
    alias = bmg.accepted_names(sources)
    seen_aliases: set[str] = set()
    for it in sources["indicators"]:
        for a in it.get("aliases") or []:
            assert a not in canonical, f"别名 {a} 撞了规范名"
            assert a not in seen_aliases, f"别名 {a} 重复"
            seen_aliases.add(a)
    assert alias["利息净收入"] == "净利息收入"


def test_alias_input_normalizes_to_canonical(sources):
    """面板标签（别名）摄入后应落到规范名的观测行上。"""
    rows, trace = bmg.to_observations(
        [_row("利息净收入", "601398", 2024, 637405000000.0)], sources)
    assert trace["unmapped"] == []
    assert rows[0]["indicator_zh"] == "净利息收入"
    assert rows[0]["concept"] == "financials.net_interest_income"


def test_variables_deduped_and_ordered(sources):
    cols = bmg.variables(sources)
    assert len(cols) == len(set(cols))
    assert cols[0] == sources["indicators"][0]["gta_name"]


def test_source_declares_unit_and_lag(sources):
    src = sources["source"]
    assert src["value_unit"] == "元"
    assert src["lag_fiscal_years"] == 1
    assert "lag_evidence" in src


# --- 观测行构造 ---------------------------------------------------------------

def _row(ind, firm, year, value):
    return {"indicator_zh": ind, "firm_id": firm, "year": year, "value": value}


def test_observation_carries_caliber_and_source(sources):
    rows, trace = bmg.to_observations([_row("客户存款", "600036", 2024, 9195329000000.0)],
                                      sources)
    assert trace["unmapped"] == [] and trace["bad"] == []
    r = rows[0]
    assert r["concept"] == "financials.customer_deposits"
    assert r["source_used"] == "gta-panel"
    assert r["unit"] == "currency"
    assert r["date"] == "2024-12-31" and r["granularity"] == "year"
    assert r["entity_code"] == "600036"
    assert "应计利息" in r["caliber"], "口径说明必须随行落库，否则读数面无从判别"


def test_short_firm_code_is_zero_padded(sources):
    rows, _ = bmg.to_observations([_row("客户存款", "2", 2024, 1.0)], sources)
    assert rows[0]["entity_code"] == "000002"


def test_duplicate_points_collapse(sources):
    rows, _ = bmg.to_observations(
        [_row("客户存款", "000001", 2024, 1.0), _row("客户存款", "000001", 2024, 1.0)],
        sources)
    assert len(rows) == 1


def test_lagging_year_is_traced_empty_not_backfilled(sources):
    """FY2025 面板无值 ⇒ 留痕 source_empty，且**不得**回填上一年值。"""
    rows, trace = bmg.to_observations(
        [_row("客户存款", "601398", 2024, 34836973000000.0)], sources,
        years=[2024, 2025])
    assert [r["year"] for r in rows] == [2024]
    assert {"indicator_zh": "客户存款", "year": 2025,
            "reason": "source_empty"} in trace["empty_years"]
    assert all(r["year"] != 2025 for r in rows)


def test_partial_year_coverage_is_not_reported_as_source_empty(sources):
    """个别银行某年未披露 ≠ 源不可用：有任意一行为值的年份不进 empty_years。"""
    _, trace = bmg.to_observations(
        [_row("客户存款", "601398", 2024, 1.0)], sources, years=[2024])
    assert trace["empty_years"] == []


def test_unmapped_indicator_name_is_traced(sources):
    rows, trace = bmg.to_observations([_row("营业收入", "600036", 2024, 1.0)], sources)
    assert rows == []
    assert trace["unmapped"] == ["营业收入"]


def test_non_numeric_value_is_rejected_not_coerced(sources):
    """面板里出现字符串（如 '—'）时必须留痕丢弃，SHALL NOT 当 0 记。"""
    rows, trace = bmg.to_observations([_row("客户存款", "600036", 2024, "—")], sources)
    assert rows == []
    assert len(trace["bad"]) == 1


def test_to_millions_helper():
    assert bmg.to_millions(34836973000000.0) == 34836973.0


# --- 核锚 ---------------------------------------------------------------------

def _golden_one(ind="客户存款", firm="600036", year=2024, value=9195329000000):
    return {"anchors": [{"indicator_zh": ind, "firm_id": firm, "year": year,
                         "value": value, "evidence": "测试用"}]}


def test_verify_anchor_match():
    res = bmg.verify_anchors([_row("客户存款", "600036", 2024, 9195329000000.0)],
                             _golden_one())
    assert res["checked"] == 1 and res["mismatched"] == [] and res["missing"] == []


def test_verify_anchor_mismatch_is_reported():
    """差的不能是「邻近信号」：这里故意用上一年值充当今年，必须判红。"""
    res = bmg.verify_anchors([_row("客户存款", "600036", 2024, 8240498000000.0)],
                             _golden_one())
    assert len(res["mismatched"]) == 1
    assert res["mismatched"][0]["got"] == 8240498000000.0


def test_verify_anchor_missing_is_reported_not_passed():
    res = bmg.verify_anchors([_row("客户存款", "600036", 2023, 8240498000000.0)],
                             _golden_one())
    assert res["checked"] == 0
    assert len(res["missing"]) == 1


def test_verify_accepts_float_noise():
    res = bmg.verify_anchors([_row("客户存款", "600036", 2024, 9195329000000.4)],
                             _golden_one())
    assert res["mismatched"] == []


# --- 仓库内锚文件 -------------------------------------------------------------

def test_golden_anchors_have_report_evidence(golden):
    assert golden["unit"] == "元"
    for a in golden["anchors"]:
        assert a["evidence"].strip(), f"{a['indicator_zh']} 锚缺证据"
        assert a["value"] > 0
        assert len(str(a["firm_id"])) == 6


def test_golden_covers_every_available_indicator(sources, golden):
    """每一项「有源」指标至少一条锚，否则启用没有把门的东西。"""
    anchored = {a["indicator_zh"] for a in golden["anchors"]}
    for it in sources["indicators"]:
        assert it["indicator_zh"] in anchored, f"{it['indicator_zh']} 无锚"


# --- 盘点判定 -----------------------------------------------------------------

def test_inventory_overrides_fixable_verdict_for_served(sources):
    """已由面板覆盖的项，盘点不能再写「可修（休眠）」——那会把人送去修已证伪的路。"""
    v = bmg.inventory_verdict("客户存款", "可修（休眠：applies_to 双层）", sources)
    assert v.startswith("已覆盖")
    assert "a0b2103201" in v and "应计利息" in v


def test_inventory_overrides_non_report_verdict_for_unavailable(sources):
    v = bmg.inventory_verdict("不良率", "非报告口径", sources)
    assert v.startswith("无源覆盖")
    assert "不修报告" in v


def test_inventory_keeps_base_verdict_for_unlisted(sources):
    """不在口径表里的指标（比例型）保持原判词。"""
    assert bmg.inventory_verdict("流动性比例（人民币）", "可用", sources) == "可用"


def test_every_money_indicator_is_classified(sources):
    """12 项金额指标都必须被接管判定，无一漏到旧判词。"""
    for ind in [i["indicator_zh"] for i in sources["indicators"]]:
        assert bmg.inventory_verdict(ind, "可修（休眠：apps_to）", sources).startswith("已覆盖")
    for ind in bmg.unavailable_reasons(sources):
        assert bmg.inventory_verdict(ind, "可修（休眠：apps_to）", sources).startswith("无源覆盖")


# --- 滞后统计 -----------------------------------------------------------------

def test_lag_note_counts_per_year(sources):
    vals = [_row("客户存款", "601398", 2024, 1.0), _row("客户存款", "600036", 2024, 1.0)]
    note = bmg.lag_note(sources, [2024, 2025], vals)
    assert note["客户存款"] == {2024: 2, 2025: 0}
    assert note["净利息收入"] == {2024: 0, 2025: 0}
