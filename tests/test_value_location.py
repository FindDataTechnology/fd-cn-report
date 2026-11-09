"""抽取出来的数字必须能定位到"哪一页哪一段"，不能只给一个 PDF URL。

审计 06 §10。`_value_obj` 的 `provenance` 记的是 **`pdf_url`**——文档，不是文档里的位置。
而一个字段的价值恰恰在"哪张表的哪个单元格"：数字有争议时，光有 URL 没有 `page`、
没有匹配到的段名、没有抽取输入，等于没法复核。

原料其实就在手边：`_resolve_section` 收 `page_offsets` / `page_count`、回 `matched`（命中的段名），
调用点两样都有——只是没往 `_value_obj` 里传。

本文件钉住：抽取值必须带 `location`（至少含命中的段名），且 `page` 能从 `page_offsets` 算出来。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import indicators_client as IC  # noqa: E402


RULE = {"name": "营业总收入", "unit": "元", "source_type": "report"}


def test_value_obj_carries_a_location_when_given_one():
    """给了位置就必须原样带出来（基本契约）。"""
    obj = IC._value_obj(
        1.0, rule=RULE, source="report:利润表", extractor="llm", period="FY",
        provenance="https://x/y.pdf",
        location={"page": 3, "section": "利润表", "char_start": 1200},
    )
    assert obj["location"]["page"] == 3
    assert obj["location"]["section"] == "利润表"


def test_value_obj_defaults_location_to_none_not_missing():
    """没给位置时字段要在（值为 None），别让它"不存在"——那是另一种沉默。"""
    obj = IC._value_obj(1.0, rule=RULE, source="s", extractor="llm", period="FY")
    assert "location" in obj, "location 字段缺失 —— 消费方无法区分「没有位置」与「不知道有这回事」"
    assert obj["location"] is None


def test_page_is_derived_from_page_offsets():
    """`page_offsets` 能把字符偏移换算成页码。"""
    # 三页：第 1 页 [0,100)，第 2 页 [100,250)，第 3 页 [250,...)
    offsets = [0, 100, 250]
    assert IC._page_for_offset(offsets, 0) == 1
    assert IC._page_for_offset(offsets, 99) == 1
    assert IC._page_for_offset(offsets, 100) == 2
    assert IC._page_for_offset(offsets, 249) == 2
    assert IC._page_for_offset(offsets, 250) == 3
    assert IC._page_for_offset(offsets, 9999) == 3


def test_page_derivation_survives_empty_or_bad_input():
    """没有 page_offsets 时不许崩，返回 None（未知 != 第 1 页）。"""
    assert IC._page_for_offset(None, 500) is None
    assert IC._page_for_offset([], 500) is None
