#!/usr/bin/env python
"""摘除银行监管指标集的确定性抽取器（awaken-banking-report-ingest 3.2）。

**为什么摘**：`script_rules` 里的 `percent_value` 规则在抽取链中**先于 LLM 命中并且
胜出**（`indicators_client._run_extractor`：先 `_try_script_extractor`，命中即返回）。
而 `percent_value` 的语义是「名称所在行或其后的第一个百分比」，**不认标签边界**，
在银行年报的密集指标表上会错行，且错得静默（value 有值、无告警）：

  601398 工商银行 2025 年报实测（真值来自正文，人工核过）：
    资本充足率      script 给 213.6   ← 真值 18.76（213.6 是拨备覆盖率的值）
    一级资本充足率   script 给 13.57   ← 真值 14.94（13.57 是核心一级的值）

  同批 `percent_value` 也有蒙对的（拨备覆盖率 213.6、核心一级 13.57、流动性覆盖率
  138.61 都对）——**蒙对与错行无法从返回值区分**，这才是必须摘掉的理由，而不是
  「这两条恰好错」。

对照实验（绕过脚本路径，直接 `_llm_extract_section` + 修好的 note 消歧）：
    资本充足率 18.76 / 一级资本充足率 14.94 / 核心一级资本充足率 13.57 —— LLM 全对。

因此本 change 内：银行监管指标集**只走 LLM 路径**，再由 golden 锚（4.2）兜底校验。

**可逆**：删除前把整行（含 module/subgroup/applies_to/position 等全部列）导成 JSON，
`--restore <file>` 原样写回（按 id 覆盖，幂等）。

用法：
  python3 scripts/retire_bank_script_rules.py --dry-run
  python3 scripts/retire_bank_script_rules.py                 # 备份 + 删除
  python3 scripts/retire_bank_script_rules.py --restore output/bank-rules/script-rules-<stamp>.json
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

#: 与 scripts/seed_bank_regulatory_rules.py 的 BANK_INDICATORS 保持一致
BANK_INDICATORS = [
    "净息差", "净利差", "不良贷款率", "不良贷款余额", "拨备覆盖率", "拨贷比",
    "资本充足率", "核心一级资本充足率", "一级资本充足率", "流动性覆盖率",
    "成本收入比", "正常类贷款迁徙率", "关注类贷款迁徙率", "次级类贷款迁徙率",
    "可疑类贷款迁徙率", "杠杆率", "净稳定资金比例",
]


def _dump(conn: sqlite3.Connection) -> list[dict]:
    marks = ", ".join("?" for _ in BANK_INDICATORS)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT * FROM script_rules WHERE indicator IN ({marks}) ORDER BY id",
        BANK_INDICATORS,
    ).fetchall()
    return [dict(r) for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--restore", help="从备份 JSON 还原（不删任何东西）")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"DB 不存在：{db}")
    conn = sqlite3.connect(str(db), timeout=30)

    if args.restore:
        rows = json.loads(Path(args.restore).read_text(encoding="utf-8"))
        conn.row_factory = sqlite3.Row
        cols = [r[1] for r in conn.execute("PRAGMA table_info(script_rules)")]
        n = 0
        for row in rows:
            payload = {k: row.get(k) for k in cols if k in row}
            names = list(payload)
            conn.execute(
                f"INSERT OR REPLACE INTO script_rules ({', '.join(names)}) "
                f"VALUES ({', '.join('?' for _ in names)})",
                [payload[c] for c in names],
            )
            n += 1
        if not args.dry_run:
            conn.commit()
        print(f"restored={n} dry_run={args.dry_run}")
        conn.close()
        return 0

    rows = _dump(conn)
    if not rows:
        print("没有匹配的 script_rules 行（可能已摘除）")
        conn.close()
        return 0

    by_ind = {}
    for r in rows:
        by_ind.setdefault(r["indicator"], []).append(f"{r['document_type']}:{r['extract_rule']}")
    for ind, specs in sorted(by_ind.items()):
        print(f"  {ind:12s} {len(specs)} 条  {specs}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = OUT_DIR / f"script-rules-{stamp}.json"
    if not args.dry_run:
        backup.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8")

    marks = ", ".join("?" for _ in BANK_INDICATORS)
    deleted = 0
    if not args.dry_run:
        cur = conn.execute(f"DELETE FROM script_rules WHERE indicator IN ({marks})",
                           BANK_INDICATORS)
        deleted = cur.rowcount
        conn.commit()
    conn.close()

    left = 0 if not args.dry_run else len(rows)
    print(f"\nmatched={len(rows)} deleted={deleted} dry_run={args.dry_run} "
          f"backup={backup if not args.dry_run else '(dry-run 不写)'}")
    print("还原：python3 scripts/retire_bank_script_rules.py --restore <backup.json>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
