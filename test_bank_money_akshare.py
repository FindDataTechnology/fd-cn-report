"""akshare 金额指标取数的离线单测（不联网）。

真值核验（对 akshare 的实弹）走
``scripts/register_bank_money_from_akshare.py --verify --cross-check``。
"""
import pandas as pd
import pytest

import bank_money_akshare as BMA
import bank_money_gta as BMG


@pytest.fixture(scope="module")
def sources():
    return BMA.load_sources()


# --- 代码形态 -----------------------------------------------------------------

@pytest.mark.parametrize("code,expect", [
    ("601398", "SH601398"), ("600036", "SH600036"), ("688111", "SH688111"),
    ("000001", "SZ000001"), ("002807", "SZ002807"), ("300015", "SZ300015"),
    ("430047", "BJ430047"),
])
def test_code_to_symbol(code, expect):
    assert BMA.code_to_symbol(code) == expect


def test_code_to_symbol_short_code_is_padded():
    assert BMA.code_to_symbol("1") == "SZ000001"


def test_code_to_symbol_rejects_unknown():
    """7 开头是申购/配号代码，不是可交易的 A 股/B 股前缀——必须拒，不能猜交易所。"""
    with pytest.raises(ValueError):
        BMA.code_to_symbol("777777")


def test_code_to_symbol_honours_explicit_exchange():
    assert BMA.code_to_symbol("601398", exchange="sh") == "SH601398"


# --- 报表帧 → 面板行 -----------------------------------------------------------

def _bs(rows):
    return pd.DataFrame(rows)


def test_annual_periods_only(sources):
    """只取 12-31 年报口径；季报不得混进来（yearly 概念装季频会重演 granularity 退化）。"""
    bs = _bs([
        {"REPORT_DATE": "2024-09-30", "ACCEPT_DEPOSIT": 1.0, "LOAN_ADVANCE": 2.0},
        {"REPORT_DATE": "2024-12-31", "ACCEPT_DEPOSIT": 3.0, "LOAN_ADVANCE": 4.0},
    ])
    rows, _ = BMA.periods_from_sheets({"balance": bs}, "601398", sources, years=[2024])
    assert {r["indicator_zh"] for r in rows} == {"客户存款", "发放贷款及垫款"}
    assert all(r["year"] == 2024 for r in rows)
    dep = next(r for r in rows if r["indicator_zh"] == "客户存款")
    assert dep["value"] == 3.0 and dep["period"] == "2024-12-31"


def test_profit_statement_columns(sources):
    ps = _bs([{"REPORT_DATE": "2025-12-31", "INTEREST_NI": 635126000000.0,
               "FEE_COMMISSION_NI": 111171000000.0}])
    rows, _ = BMA.periods_from_sheets({"profit": ps}, "601398", sources, years=[2025])
    by = {r["indicator_zh"]: r["value"] for r in rows}
    assert by["净利息收入"] == 635126000000.0
    assert by["手续费及佣金净收入"] == 111171000000.0


def test_missing_statement_is_traced_not_fatal(sources):
    rows, trace = BMA.periods_from_sheets({"balance": _bs([])}, "601398", sources, years=[2024])
    assert rows == []
    assert {t["reason"] for t in trace} == {"statement-missing"}


def test_nan_value_is_traced(sources):
    bs = _bs([{"REPORT_DATE": "2024-12-31", "ACCEPT_DEPOSIT": float("nan"),
               "LOAN_ADVANCE": 5.0}])
    rows, trace = BMA.periods_from_sheets({"balance": bs}, "601398", sources, years=[2024])
    assert [r["indicator_zh"] for r in rows] == ["发放贷款及垫款"]
    assert any(t["reason"] == "value-missing" and t["indicator_zh"] == "客户存款"
               for t in trace)


def test_years_filter(sources):
    bs = _bs([{"REPORT_DATE": f"{y}-12-31", "ACCEPT_DEPOSIT": 1.0, "LOAN_ADVANCE": 1.0}
              for y in (2022, 2023, 2024)])
    rows, _ = BMA.periods_from_sheets({"balance": bs}, "601398", sources, years=[2024])
    assert {r["year"] for r in rows} == {2024}


# --- 交叉校验 -----------------------------------------------------------------

def _row(ind, firm, year, val):
    return {"indicator_zh": ind, "firm_id": firm, "year": year, "value": val}


def test_cross_check_identical_sources_pass():
    ak = [_row("客户存款", "601398", 2024, 34836973000000.0)]
    cc = BMA.cross_check(ak, ak)
    assert cc["compared"] == 1 and cc["mismatched"] == []


def test_cross_check_detects_drift():
    """口径漂移必须判红：这里拿「本金」冒充「含应计利息」。"""
    ak = [_row("客户存款", "600036", 2024, 9195329000000.0)]
    gta = [_row("客户存款", "600036", 2024, 9096587000000.0)]
    cc = BMA.cross_check(ak, gta)
    assert len(cc["mismatched"]) == 1
    assert cc["mismatched"][0]["akshare"] == 9195329000000.0


def test_cross_check_reports_one_sided_points():
    ak = [_row("客户存款", "601398", 2025, 1.0)]
    gta = [_row("客户存款", "601398", 2024, 1.0)]
    cc = BMA.cross_check(ak, gta)
    assert cc["compared"] == 0
    assert cc["only_akshare"] == [{"indicator_zh": "客户存款", "firm_id": "601398", "year": 2025}]
    assert cc["only_gta"] == [{"indicator_zh": "客户存款", "firm_id": "601398", "year": 2024}]


def test_cross_check_reports_non_numeric_gta_values_separately():
    """非数值的 GTA 值不得静默消失：要单列出来，让人能看见。"""
    ak = [_row("客户存款", "601398", 2024, 1.0)]
    cc = BMA.cross_check(ak, [_row("客户存款", "601398", 2023, None)])
    assert cc["compared"] == 0
    assert cc["uncomparable_gta"] == [
        {"indicator_zh": "客户存款", "firm_id": "601398", "year": 2023}]
    assert cc["only_akshare"] == [
        {"indicator_zh": "客户存款", "firm_id": "601398", "year": 2024}]


# --- 与观测行构造的衔接 -------------------------------------------------------

def test_akshare_rows_flow_into_observations(sources):
    rows = [_row("客户存款", "600036", 2025, 9924558000000.0)]
    obs, trace = BMG.to_observations(rows, sources, source_used="akshare")
    assert trace["unmapped"] == []
    assert obs[0]["source_used"] == "akshare"
    assert obs[0]["concept"] == "financials.customer_deposits"
    assert obs[0]["date"] == "2025-12-31"


def test_no_lag_for_akshare(sources):
    """akshare 声明零滞后：不得出现「整年无值」的滞后留痕（反例见 GTA 的 2025）。"""
    assert sources["source_akshare"]["lag_fiscal_years"] == 0
    rows = [_row("客户存款", "601398", 2025, 37311778000000.0)]
    _, trace = BMG.to_observations(rows, sources, years=[2025], source_used="akshare")
    assert trace["empty_years"] == []
