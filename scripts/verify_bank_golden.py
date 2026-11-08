#!/usr/bin/env python
"""银行监管指标 golden 锚复算闸（awaken-banking-report-ingest 4.2）。

锚在 `docs/golden-bank-indicators.json`：17 项指标 × 5 家试点（85 条），值全部来自
`reports/banking-report-ingest/pilot-verification-2026-11-08.md` 的逐值人工核对。
本脚本把锚**重新抽一遍**并逐值比对，可作回归闸：

  python3 scripts/verify_bank_golden.py                    # 全部锚
  python3 scripts/verify_bank_golden.py --entity 601288    # 单家
  python3 scripts/verify_bank_golden.py --strict-miss      # 未披露也判失败

**对位失败不出数纪律**（spec「银行监管指标组 SHALL 齐备并以 golden 锚验证」）：
抽取返回 ``None`` 时**不得**补 0、不得插值。本脚本把「无值」分成两种，判定口径不同：

  · `未披露`   —— 全文里根本没有该指标标签（报告确实没披露）→ 正常，非缺陷
  · `对位失败` —— 标签在原文出现，但抽取没拿到值 → **缺陷**，非零退出

这保证「没有值」永远不会被当成「值为 0」，也让「切错段/漏抽」无法伪装成「未披露」。

退出码：0 全通过；1 有值不一致或对位失败（`--strict-miss` 时未披露也算失败）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

GOLDEN = _REPO / "docs" / "golden-bank-indicators.json"
CACHE_DIR = _REPO / ".cache" / "reports"

#: 各指标在报告里的原文标签（判断「未披露」用；与选择器链的段名无关）
LABELS: dict[str, list[str]] = {
    "净息差": ["净息差", "净利息收益率"],
    "净利差": ["净利差", "净利息差"],
    "不良贷款率": ["不良贷款率"],
    "不良贷款余额": ["不良贷款"],
    "拨备覆盖率": ["拨备覆盖率"],
    "拨贷比": ["拨贷比", "贷款拨备率"],
    "资本充足率": ["资本充足率"],
    "核心一级资本充足率": ["核心一级资本充足率"],
    "一级资本充足率": ["一级资本充足率"],
    "流动性覆盖率": ["流动性覆盖率"],
    "成本收入比": ["成本收入比"],
    "杠杆率": ["杠杆率"],
    "净稳定资金比例": ["净稳定资金比例"],
    "正常类贷款迁徙率": ["正常类贷款迁徙率", "正常贷款迁徙率", "贷款迁徙率"],
    "关注类贷款迁徙率": ["关注类贷款迁徙率", "关注类"],
    "次级类贷款迁徙率": ["次级类贷款迁徙率", "次级类"],
    "可疑类贷款迁徙率": ["可疑类贷款迁徙率", "可疑类"],
    "流动性比例（人民币）": ["流动性比例", "流动性比率"],
}

TOL = 1e-6  # 只允许浮点表示误差


def _report_text(code: str, year: int, form: str) -> str:
    pats = [f"{code}_{year}_{form}_*.txt", f"{code}_{year}_*.txt"]
    for pat in pats:
        hits = sorted(CACHE_DIR.glob(pat))
        if hits:
            return hits[0].read_text(encoding="utf-8", errors="replace")
    return ""


def disclose_status(indicator: str, value, text: str) -> str:
    """把「无值」分成 未披露 / 对位失败；有值返回 ok。

    对位失败要求原文**真的给了数**（标签后 60 字符内出现数字）——只看标签出现过会把
    叙述式提及（「本行资本充足率保持稳健」）误判成缺陷。
    """
    if value is not None:
        return "ok"
    flat = re.sub(r"\s+", "", text or "")
    for label in LABELS.get(indicator, [indicator]):
        needle = re.sub(r"\s+", "", label)
        start = 0
        while True:
            pos = flat.find(needle, start)
            if pos == -1:
                break
            if re.search(r"\d", flat[pos + len(needle):pos + len(needle) + 60]):
                return "对位失败"
            start = pos + 1
    return "未披露"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--golden", default=str(GOLDEN))
    ap.add_argument("--entity", help="只跑某家（代码）")
    ap.add_argument("--strict-miss", action="store_true", help="未披露也判失败")
    args = ap.parse_args()

    doc = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    prompts: dict[tuple[str, int, str], list[str]] = {}
    for ind, anchors in doc["indicators"].items():
        for a in anchors:
            if args.entity and a["entity_code"] != args.entity:
                continue
            prompts.setdefault((a["entity_code"], a["fiscal_year"], a["form"]), []).append(ind)

    if not prompts:
        print("没有匹配的锚")
        return 1

    import indicators_client as IC

    results: dict[tuple[str, int, str], dict] = {}
    bad = 0
    for (code, year, form), inds in sorted(prompts.items()):
        bundle = IC.extract_indicators(code, year, indicators=inds, form=form,
                                       extractor_mode="llm")
        got = bundle.get("indicators") or {}
        text = _report_text(code, year, form)
        for ind in inds:
            val = (got.get(ind) or {}).get("value")
            status = disclose_status(ind, val, text)
            results[(code, year, form, ind)] = {"value": val, "status": status}

    print(f"{'银行':<8}{'指标':<14}{'锚值':>16}{'抽取值':>16}  判定")
    for ind, anchors in doc["indicators"].items():
        for a in anchors:
            if args.entity and a["entity_code"] != args.entity:
                continue
            key = (a["entity_code"], a["fiscal_year"], a["form"], ind)
            r = results[key]
            val, want = r["value"], a["value"]
            if val is None:
                verdict = r["status"]
                fail = r["status"] == "对位失败" or (args.strict_miss and r["status"] == "未披露")
            elif abs(float(val) - float(want)) <= TOL * max(1.0, abs(float(want))):
                verdict = "ok"
                fail = False
            else:
                verdict = "值不一致"
                fail = True
            bad += 1 if fail else 0
            print(f"{a['entity_code']:<8}{ind:<14}{want:>16,.4f}{(val if val is not None else float('nan')):>16,.4f}  "
                  f"{'✗ ' if fail else '✓ '}{verdict}")

    total = sum(len(v) for v in doc["indicators"].values()) if not args.entity else \
        sum(1 for anchors in doc["indicators"].values() for a in anchors if a["entity_code"] == args.entity)
    print(f"\nanchors={total} fail={bad} strict_miss={args.strict_miss}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
