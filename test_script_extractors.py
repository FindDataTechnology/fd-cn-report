"""`script_extractors` 金额符号归一化的离线单测（纯函数，不联网、不读库）。

审计 06 §1 / `harden-ponytail-p0` 任务 3.2：`_NUM_RE` 只认 ASCII 连字符，会计
实际使用的 `(1,234.56)`、`（1,234.56）`、`－1,234.56` 三种写法都曾被解析成
**正数**，而 ``script_rules`` 的 5,531 条指标全走这条路径，错号会被缓存成
"权威值"。这里钉两件事：三种负号写法必须出负值；正数（含精度）一个字不变。
"""
from __future__ import annotations

import pytest

import script_extractors as S

AMOUNT_RULE = {"name": "营业外支出", "unit": "元"}


# --- 负数的三种会计写法 -------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "营业外支出 (1,234.56)",      # ASCII 括号
        "营业外支出 （1,234.56）",     # 全角括号
        "营业外支出 －1,234.56",       # U+FF0D 全角减号
        "营业外支出 -1,234.56",        # ASCII 连字符（修之前就只有它对）
    ],
)
def test_every_negative_form_is_negative(text):
    assert S.regex_amount(text, AMOUNT_RULE, "2024")["value"] == -1234.56


# --- 正数不受影响 -------------------------------------------------------------

def test_plain_amount_stays_positive():
    assert S.regex_amount("营业外支出 1,234.56", AMOUNT_RULE, "2024")["value"] == 1234.56


def test_positive_precision_is_unchanged():
    """归一化不能顺手改精度/千分位处理。"""
    assert S.regex_amount("营业外支出 1,234,567.89", AMOUNT_RULE, "2024")["value"] == 1234567.89


# --- 归一化在共享位置，各 extractor 都继承 ------------------------------------

def test_table_row_inherits_the_normalisation():
    text = "营业外支出 （1,234.56）"
    assert S.table_row(text, AMOUNT_RULE, "2024")["value"] == -1234.56


def test_percent_value_inherits_the_normalisation():
    rule = {"name": "毛利率", "unit": "%"}
    assert S.percent_value("毛利率 －12.5%", rule, "2024")["value"] == -12.5
    assert S.percent_value("毛利率 (12.5%)", rule, "2024")["value"] == -12.5
    assert S.percent_value("毛利率 12.5%", rule, "2024")["value"] == 12.5


# --- 别把不是负数的括号当成负数 -----------------------------------------------

def test_numbered_list_marker_is_not_a_negative():
    """（1）营业收入 是编号，不是 -1。"""
    assert S.regex_amount("营业外支出 （1）1,234.56", AMOUNT_RULE, "2024")["value"] == 1234.56


def test_year_range_dash_is_not_a_minus():
    """2023—2025 是区间，不是 -2025。"""
    assert S.regex_amount("营业外支出 2023—2025 1,234.56", AMOUNT_RULE, "2024")["value"] == 1234.56


def test_non_numeric_parentheses_are_left_alone():
    text = "营业外支出（以下简称“公司”）1,234.56"
    assert S._normalize_numbers(text) == text
