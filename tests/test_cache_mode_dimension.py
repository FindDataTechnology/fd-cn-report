"""一次 python 模式的调试运行，不能毒化该公司的整年缓存。

`extract_indicators` 把答案整体落盘，读缓存时只比 `rules_hash`；而 `rules_hash`
只覆盖规则字典与 Pydantic schema，**不含 extractor_mode**。于是：

1. `extractor_mode="python"` 跑一次 → 每条 LLM 规则都记成 `value: None` +
   note「skipped: llm extractor in python mode」，这份 bundle 照样落盘；
2. 之后普通的 `auto` 运行对同一公司/年份 hash 完全相同 → 命中，
   返回「全部 LLM 指标为 null」且 `cached: True`。

输出看起来像一次完整的抽取、只是什么都没找到——而真相是模式差异。这是本仓
最怕的静默降级：错的值没有任何入口能看出来。

修法：bundle 本来就存了 `extractor_mode`（`indicators_client.py:1571`），
所以读缓存时把它也比一遍即可，不需要改缓存键、不需要失效既有缓存。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import report_cache  # noqa: E402


@pytest.fixture()
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FD_CN_REPORT_CACHE_DIR", str(tmp_path))
    # cache_dir() 若读别的变量名，直接把它指到 tmp_path
    monkeypatch.setattr(report_cache, "cache_dir", lambda: tmp_path, raising=False)
    return tmp_path


def _write(tmp_path: Path, stem: str, bundle: dict) -> None:
    (tmp_path / f"{stem}.indicators.json").write_text(
        json.dumps(bundle, ensure_ascii=False), encoding="utf-8"
    )


def test_python_mode_bundle_is_not_served_to_auto(cache_dir, tmp_path):
    """python 模式落盘的 bundle 不得被 auto 运行当命中。"""
    stem = "abc123"
    _write(tmp_path, stem, {
        "rules_hash": "RH",
        "extractor_mode": "python",
        "indicators": {"营业收入": {"value": None, "note": "skipped: llm extractor in python mode"}},
        "cached": False,
    })

    # 同 hash、同模式 → 命中
    assert report_cache.get_cached_indicators(stem, "RH", "python") is not None
    # 同 hash、不同模式 → 必须落空，逼调用方重新抽取
    assert report_cache.get_cached_indicators(stem, "RH", "auto") is None


def test_same_mode_same_hash_still_hits(cache_dir, tmp_path):
    """加了 mode 维度之后，正常的缓存命中不能被打坏。"""
    stem = "def456"
    _write(tmp_path, stem, {
        "rules_hash": "RH2", "extractor_mode": "auto", "indicators": {"x": {"value": 1}},
    })
    got = report_cache.get_cached_indicators(stem, "RH2", "auto")
    assert got is not None and got["indicators"]["x"]["value"] == 1


def test_rule_hash_mismatch_still_misses(cache_dir, tmp_path):
    """规则集变了仍然要落空（原有行为不许退化）。"""
    stem = "ghi789"
    _write(tmp_path, stem, {"rules_hash": "OLD", "extractor_mode": "auto", "indicators": {}})
    assert report_cache.get_cached_indicators(stem, "NEW", "auto") is None


def test_legacy_bundle_without_mode_is_re_extracted(cache_dir, tmp_path):
    """加字段之前落的 bundle 没有 extractor_mode → 宁可重抽一次，也不冒风险。"""
    stem = "jkl012"
    _write(tmp_path, stem, {"rules_hash": "RH3", "indicators": {"y": {"value": 2}}})
    assert report_cache.get_cached_indicators(stem, "RH3", "auto") is None
    # 不传 expected_mode 的旧调用方行为不变（向后兼容）
    assert report_cache.get_cached_indicators(stem, "RH3") is not None
