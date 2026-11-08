#!/usr/bin/env python
"""降层 `llm_rules` 四个 JSON 列的双层编码（`applies_to` 全库 3370 行受影响）。

**缺陷**：`llm_rules.applies_to` 全库被写成「JSON 字符串套 JSON」
（`"{\\"industry\\": \\"bank\\", ...}"`），而读取面 `LlmRuleV2.to_rule_dict()` **只解一层**，
于是拿到的是一个 `str`；`indicators_client.applies_to()` 对 str 只放行
`"*" / "null" / "None"` 三个字面量 —— **所有带行业范围的规则一直静默判「不适用」**。
症状是「规则在库里、抽取却不出数」，且无任何告警。

修复就是把这些列**降一层**（`json.dumps(json.loads(json.loads(raw)))`）。

⚠️ 必须**四列一起降**（`applies_to` / `source` / `aliases` / `value_range`）：只降 `applies_to`
会让规则重新"适用"，然后立刻在 `_resolve_via_akshare` 上崩——实测 13 条银行规则降完 applies_to
后报 `AttributeError: 'str' object has no attribute 'get'`，因为 `source` 也是双层，
`src.get("statement")` 拿到的是 str。

**影响面（2026-11-08 干跑实测）**：3392 行里 3370 行是双层。
  · 3345 行内层 `industry` 是 `null`/`*`（全行业）→ 修前修后行为一致，纯编码整洁
  · **25 行修好后会「新生效」**：bank 13 / insurance 11 / securities 1
    这些是真的行为变更（从"静默不适用"变成"按行业范围生效"），必须由对应条线确认

因此本脚本**默认只修一个行业**，跨条线的行业自行决定：

  python3 scripts/repair_applies_to_encoding.py --dry-run --scope bank
  python3 scripts/repair_applies_to_encoding.py --scope bank
  python3 scripts/repair_applies_to_encoding.py --all            # 全量（含 3345 条无害项）
  python3 scripts/repair_applies_to_encoding.py --scope insurance,securities

安全：改前把命中行**原样导出**到 `output/bank-rules/applies-to-<scope>-<stamp>.json`；
`--restore <file>` 可按 id 覆盖写回。幂等：只处理双层行，复跑 changed=0。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
DEFAULT_DB = _REPO.parent / "daas.db"
OUT_DIR = _REPO / "output" / "bank-rules"
JSON_COLS = ("applies_to", "source", "aliases", "value_range")


def _decode_once(raw: str):
    """返回 (inner_value, 是否需要降层)。只有「解一层得到 str、再解一次得到 dict」才需要。"""
    if not raw:
        return None, False
    try:
        once = json.loads(raw)
    except (TypeError, ValueError):
        return None, False
    if not isinstance(once, str):
        return once, False
    try:
        inner = json.loads(once)
    except (TypeError, ValueError):
        return once, False  # 纯字符串，不是"编码套编码"
    return inner, True


def _industry(inner) -> str | None:
    if isinstance(inner, dict):
        return inner.get("industry")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--scope", default="bank", help="逗号分隔行业（bank/insurance/securities/*）")
    ap.add_argument("--all", action="store_true", help="全量降层（含内层 null/* 的无害行）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--restore", help="从备份 JSON 还原（按 id 覆盖写回）")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db, timeout=30)
    conn.row_factory = sqlite3.Row

    if args.restore:
        rows = json.loads(Path(args.restore).read_text(encoding="utf-8"))
        n = 0
        for row in rows:
            sets = ", ".join(f"{c} = ?" for c in JSON_COLS if c in row)
            vals = [row[c] for c in JSON_COLS if c in row] + [row["id"]]
            conn.execute(f"UPDATE llm_rules SET {sets} WHERE id = ?", vals)
            n += 1
        if not args.dry_run:
            conn.commit()
        print(f"restored={n} dry_run={args.dry_run}")
        conn.close()
        return 0

    scopes = {s.strip() for s in args.scope.split(",") if s.strip()}
    cols = ", ".join(JSON_COLS)
    todo = []
    for row in conn.execute(f"SELECT id, indicator, {cols} FROM llm_rules ORDER BY id"):
        inner, needs = _decode_once(row["applies_to"])
        # 选行依据：applies_to 双层（首轮），或 applies_to 已单层但别的 JSON 列仍双层（补修）
        other_needs = any(_decode_once(row[c])[1] for c in ("source", "aliases", "value_range"))
        if not needs and not other_needs:
            continue
        ind = _industry(inner) if needs else _industry(json.loads(row["applies_to"]) if row["applies_to"] else None)
        if args.all:
            pass  # 全量：包括内层 null/* 的无害行
        elif ind is None or ind == "*":
            continue  # 无害行（行为不变），默认不动
        elif ind not in scopes:
            continue
        # 四列里凡双层的都降；applies_to 一定降（它是选行依据）
        payload = {}
        for c in JSON_COLS:
            v, needs_c = _decode_once(row[c])
            payload[c] = json.dumps(v, ensure_ascii=False) if needs_c else row[c]
        todo.append((row["id"], row["indicator"], ind, {c: row[c] for c in JSON_COLS}, payload))

    by_ind: dict[str, int] = {}
    for _id, ind, industry, _raw, _payload in todo:
        by_ind[f"{industry}:{ind}"] = by_ind.get(f"{industry}:{ind}", 0) + 1
    print(f"待降层 {len(todo)} 行（scope={'ALL' if args.all else sorted(scopes)}）")
    for k, v in sorted(by_ind.items()):
        print(f"  {k} ×{v}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    label = "all" if args.all else "-".join(sorted(scopes))
    backup = OUT_DIR / f"applies-to-{label}-{stamp}.json"
    if todo and not args.dry_run:
        backup.write_text(json.dumps(
            [{"id": i, "indicator": ind, **raw} for i, ind, _s, raw, _p in todo],
            ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        for rid, _ind, _s, _raw, payload in todo:
            sets = ", ".join(f"{c} = ?" for c in JSON_COLS)
            conn.execute(f"UPDATE llm_rules SET {sets} WHERE id = ?",
                         [payload[c] for c in JSON_COLS] + [rid])
        conn.commit()
    conn.close()

    print(f"\nchanged={0 if args.dry_run else len(todo)} dry_run={args.dry_run} "
          f"backup={backup if todo and not args.dry_run else '(未写)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
