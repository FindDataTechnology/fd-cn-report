"""akshare 路径不许「拿错年份却标成请求的那一年」。

`_resolve_via_akshare` 先按 4 位年份挑行；挑不到时**兜底取 `data[0]`**（并假设那是
"最近一年"——这本身是对第三方端点排序的未验证假设），然后无条件写
`provenance=f"akshare row {target}"`，而 `target` 是**请求**的年份。

于是问 2021、报表里只有 2024 时，返回的是 2024 的数字，**标签却写 2021**。
同比序列会把不同年份混在一起，而每一行都自称年份正确——这比返回空值更坏，
因为空值至少是诚实的。（审计 06 §8；108 条 akshare 规则全走这条路径。）

修法：兜底时把实际年份写进 provenance，或直接返回 None + note。
本文件断言「provenance 不许声称一个它并不来自的年份」。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import indicators_client as IC  # noqa: E402


def _install_fake(monkeypatch, columns, data):
    """把 financials_client 换成只回一份固定报表的桩。"""
    fake = types.ModuleType("financials_client")

    def get_statements(stock_code, period=None, exchange=""):
        return {"利润表": {"columns": columns, "data": data}}

    fake.get_statements = get_statements
    monkeypatch.setitem(sys.modules, "financials_client", fake)


RULE = {"source": {"statement": "利润表", "field": "营业总收入"}}


def test_wrong_year_is_not_labelled_as_the_requested_year(monkeypatch):
    """只有 2024 的行，问 2021 —— 返回值的 provenance 不许写 2021。"""
    _install_fake(monkeypatch, ["报告日", "营业总收入"], [["2024-12-31", 999]])
    out = IC._resolve_via_akshare({"stock_code": "600000"}, RULE, 2021, "FY")

    prov = (out.get("provenance") or "") + (out.get("note") or "")
    value = out.get("value")

    if value is None:
        # 允许"直接拒绝"这种更严格的修法
        return
    assert "2021" not in prov or "2024" in prov, (
        f"取到了 2024 的数却把来源标成请求年份：value={value} provenance={out.get('provenance')!r}"
    )


def test_matching_year_is_still_returned_with_correct_provenance(monkeypatch):
    """正常路径不许退化：有对应年份的行时，取值与标签都要对。"""
    _install_fake(monkeypatch, ["报告日", "营业总收入"],
                  [["2024-12-31", 200], ["2021-12-31", 100]])
    out = IC._resolve_via_akshare({"stock_code": "600000"}, RULE, 2021, "FY")
    assert out.get("value") == 100, out
    assert "2021" in (out.get("provenance") or "")
