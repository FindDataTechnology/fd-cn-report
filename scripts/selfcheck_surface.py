#!/usr/bin/env python3
"""tool-surface manifest 双向 selfcheck（mcp-surface-contract，fd-cn-report 版）。

断言两个方向：
  1. **一致**：manifest 声明的工具集 == 运行时注册的工具集。
     注册表新增/删除工具而 manifest 未同步 → 失败（反向同理）。
     运行时真值取 `server.app` 的 `_list_tools()`——与上牌入口注册用的是同一个
     FastMCP 实例，故"能列出"与"能服务"必然是同一份清单。
  2. **闭合**：任何消费侧暴露的工具集 ⊆ manifest 的 commercial 集。
     消费侧由 `--consumers` 传入（pack 套件目录或 tool-surface 文件）。本服务
     目前无消费方（`skills_eligible_for_packs` 为空），故默认只做方向 1；
     有消费方后加 `--consumers` 即生效。

另断言：行为属性（readOnlyHint/destructiveHint/idempotentHint/openWorldHint）
manifest ↔ 运行时逐项相等（两个方向都查）；输出结构 declared/undeclared 与
运行时 output_schema 一致；反向上牌自检（摘条目必须报错）。

用法：
    uv run python scripts/selfcheck_surface.py                       # 方向 1 + 反向自检
    uv run python scripts/selfcheck_surface.py --consumers <dir-or-file>
    uv run python scripts/selfcheck_surface.py --gen-check            # 另跑 gen_surface --check
退出码：0 通过 / 1 失败（列出差异）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "tool-surface.json"
SERVER_NAME = "fd-cn-report"

#: 消费侧点名本服务工具时使用的完整形态：mcp__fd-cn-report__<tool>
TOOL_PATTERN = re.compile(rf"mcp__{SERVER_NAME}__([A-Za-z0-9_.\-]+)")

REQUIRED_TOP_KEYS = (
    "schema", "server", "entry_path", "product_line", "hosting",
    "description", "skills_eligible_for_packs", "tool_annotations",
    "naming_convention", "output_structure", "tool_groups", "registry",
)

REQUIRED_HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


def fail(problems: list[str]) -> None:
    print(f"✗ {len(problems)} 项不合规：", file=sys.stderr)
    for p in problems:
        print(f"  - {p}", file=sys.stderr)
    raise SystemExit(1)


def load_manifest() -> dict:
    if not MANIFEST.exists():
        fail([f"manifest 缺失：{MANIFEST}（契约：缺失即未上牌）"])
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def manifest_tools(m: dict) -> dict[str, str]:
    """工具名 → 暴露级别。"""
    out: dict[str, str] = {}
    for g in m.get("tool_groups", []):
        level = g.get("level")
        if level not in ("commercial", "internal"):
            fail([f"tool_groups.{g.get('group')} 的 level 非法：{level!r}"])
        for t in g.get("tools", []):
            if isinstance(t, dict):
                t, level = t.get("name"), t.get("level", level)
            if t in out and out[t] != level:
                fail([f"工具 {t} 在多个 group 中级别冲突"])
            out[t] = level
    return out


def runtime_tools() -> dict[str, object]:
    """运行时真值：**问真实 server 要**，不读意图模块。

    本仓曾有的风险形态：清单照"打算注册什么"写，而 server 实际注册的是另一份，
    两边各自"一致"、缺口无人发现。此处 import 上牌入口 `server` 取 `app`，用
    FastMCP 的 `_list_tools()` 枚举。server 在 import 期不连库、不联网、不调
    LLM（DB/ES/LLM 都在工具调用期才解析），故安全。
    """
    sys.path.insert(0, str(REPO))
    from server import app

    return {t.name: t for t in asyncio.run(app._list_tools())}


def check_shape(m: dict) -> list[str]:
    problems = []
    for k in REQUIRED_TOP_KEYS:
        if k not in m:
            problems.append(f"顶层缺字段：{k}")
    if m.get("schema") != "mcp-tool-surface/v1":
        problems.append(f"schema 非法：{m.get('schema')!r}")
    if m.get("server") != SERVER_NAME:
        problems.append(f"server 字段应为 {SERVER_NAME!r}，实为 {m.get('server')!r}")
    if not isinstance(m.get("hosting"), list) or not m["hosting"]:
        problems.append("hosting 应为非空列表")
    mt = manifest_tools(m)
    expected = (m.get("registry") or {}).get("expected_tool_count")
    if expected != len(mt):
        problems.append(
            f"registry.expected_tool_count={expected} 与 manifest 实收 {len(mt)} 不符"
        )
    return problems


def check_runtime_agreement(m: dict) -> list[str]:
    """方向 1：manifest ↔ 运行时一致。"""
    man = set(manifest_tools(m))
    run = set(runtime_tools())
    problems = []
    added = sorted(run - man)
    removed = sorted(man - run)
    if added:
        problems.append(f"运行时有而 manifest 无（需登记进 tool_groups）：{added}")
    if removed:
        problems.append(f"manifest 有而运行时无（需从 tool_groups 删除）：{removed}")
    return problems


def runtime_annotations(runtime: dict[str, object]) -> dict[str, dict]:
    """运行时真值：每个工具在协议层实际声明的属性（不读 surface 意图）。"""
    out: dict[str, dict] = {}
    for name, t in runtime.items():
        a = t.annotations
        out[name] = {} if a is None else {
            "readOnlyHint": a.readOnlyHint,
            "destructiveHint": a.destructiveHint,
            "idempotentHint": a.idempotentHint,
            "openWorldHint": a.openWorldHint,
        }
    return out


def check_annotations(m: dict, runtime: dict[str, object]) -> list[str]:
    """manifest 行为属性 ↔ 运行时注册值逐项相等（两个方向都查）。

    漏登记 → 客户端拿到 None；谎报只读 → 客户端自动批准一个写库工具。
    两者都是上牌缺陷，故一律失败并点名工具+字段。
    """
    declared = m.get("tool_annotations")
    if not isinstance(declared, dict):
        return ["manifest 缺 tool_annotations（行为属性须随工具一并上牌）"]
    rt = runtime_annotations(runtime)
    man_tools = set(manifest_tools(m))
    problems: list[str] = []
    for name in sorted(man_tools - set(declared)):
        problems.append(f"{name}: manifest 未声明行为属性")
    for name in sorted(set(declared) - man_tools):
        problems.append(f"{name}: tool_annotations 登记了未上牌的工具")
    for name in sorted(man_tools & set(declared)):
        d = declared[name]
        missing = [k for k in REQUIRED_HINTS if k not in d]
        if missing:
            problems.append(f"{name}: 属性不全，缺 {missing}")
            continue
        for k in REQUIRED_HINTS:
            if rt.get(name, {}).get(k) != d[k]:
                problems.append(
                    f"{name}.{k}: manifest 声明 {d[k]!r} 与运行时 {rt.get(name, {}).get(k)!r} 不符"
                )
    # 写面工具必须显式 destructive/非幂等语义自洽（上牌口径护栏，非 MCP 规范）
    for name in sorted(man_tools & set(declared)):
        d = declared[name]
        if d.get("readOnlyHint") is False and d.get("destructiveHint") is not True \
                and name not in ("index_records", "audit_rule_gaps",
                                 "open_industry_rules_dashboard"):
            problems.append(f"{name}: readOnly=false 但 destructive 未标 true（口径存疑）")
    return problems


def runtime_output_schema_tools(runtime: dict[str, object]) -> set[str]:
    return {n for n, t in runtime.items() if getattr(t, "output_schema", None)}


def check_output_structure(m: dict, runtime: dict[str, object]) -> list[str]:
    """输出结构声明（mcp-result-contract）：无静默空缺。"""
    block = m.get("output_structure")
    if not isinstance(block, dict):
        return ["manifest 缺 output_structure（输出结构状态须显式可见）"]
    declared = set(block.get("declared") or [])
    undeclared = set(block.get("undeclared") or [])
    man_tools = set(manifest_tools(m))
    problems: list[str] = []

    both = sorted(declared & undeclared)
    if both:
        problems.append(f"同时出现在 declared 与 undeclared：{both}")
    silent = sorted(man_tools - declared - undeclared)
    if silent:
        problems.append(f"既未声明也未登记为未声明（静默空缺）：{silent}")
    stray = sorted((declared | undeclared) - man_tools)
    if stray:
        problems.append(f"output_structure 登记了未上牌的工具：{stray}")

    runtime_has = runtime_output_schema_tools(runtime)
    claimed_but_absent = sorted(declared - runtime_has)
    if claimed_but_absent:
        problems.append(f"manifest 声称已声明，运行时却无 output_schema：{claimed_but_absent}")
    present_but_unlisted = sorted(runtime_has - declared)
    if present_but_unlisted:
        problems.append(f"运行时有 output_schema 但 manifest 未列入 declared：{present_but_unlisted}")
    return problems


def _iter_consumer_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    out: list[Path] = []
    for pat in ("*.json", "*.md"):
        out.extend(sorted(target.rglob(pat)))
    return out


def check_consumers(m: dict, target: Path) -> list[str]:
    """方向 2：消费侧暴露集 ⊆ manifest commercial 集。"""
    levels = manifest_tools(m)
    commercial = {t for t, lv in levels.items() if lv == "commercial"}
    problems = []
    seen: set[str] = set()
    for f in _iter_consumer_files(target):
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for tool in TOOL_PATTERN.findall(text):
            seen.add(tool)
            if tool not in levels:
                problems.append(f"{f.name}: 点名了 manifest 未登记的工具 {tool}")
            elif tool not in commercial:
                problems.append(f"{f.name}: 点名了非 commercial 工具 {tool}（级别 {levels[tool]}）")
    if not seen:
        print(f"· 消费侧 {target} 未点名任何 {SERVER_NAME} 工具（无可校验项）")
    return problems


def check_unsurfaced_ok() -> list[str]:
    """反向上牌自检：故意摘掉一个条目的比对必须**失败**，否则本脚本形同虚设。

    做法：构造一份缺一个工具的 manifest 副本，断言方向 1 会报出该工具。
    """
    m = load_manifest()
    man = manifest_tools(m)
    if not man:
        return ["manifest 无工具，无法做反向上牌自检"]
    victim = sorted(man)[0]
    broken = json.loads(json.dumps(m))
    for g in broken["tool_groups"]:
        if victim in g["tools"]:
            g["tools"].remove(victim)
            break
    diff = check_runtime_agreement(broken)
    if not any(victim in d for d in diff):
        return [f"反向自检失败：摘掉 {victim} 后方向 1 未报出该工具（脚本形同虚设）"]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consumers", type=Path, default=None,
                    help="消费侧目录或文件（pack 套件 / tool-surface）")
    ap.add_argument("--gen-check", action="store_true",
                    help="另跑 gen_surface.py --check（生成器视角的漂移比对）")
    args = ap.parse_args()

    m = load_manifest()
    runtime = runtime_tools()
    problems = check_shape(m)
    problems += check_runtime_agreement(m)
    problems += check_annotations(m, runtime)
    problems += check_output_structure(m, runtime)
    if args.consumers:
        problems += check_consumers(m, args.consumers)
    problems += check_unsurfaced_ok()

    if args.gen_check:
        rc = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "gen_surface.py"), "--check"],
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            problems.append(f"gen_surface --check 失败：{rc.stdout.strip()} {rc.stderr.strip()}")

    if problems:
        fail(problems)

    man = manifest_tools(m)
    ann = m.get("tool_annotations", {})
    ro = sum(1 for name in man if ann.get(name, {}).get("readOnlyHint") is True)
    by_level: dict[str, int] = {}
    for lv in man.values():
        by_level[lv] = by_level.get(lv, 0) + 1
    summary = " / ".join(f"{k} {v}" for k, v in sorted(by_level.items()))
    print(f"✓ selfcheck 通过：{len(man)} 工具（{summary}）｜"
          f"只读 {ro} / 写面 {len(man) - ro}｜分组 {len(m['tool_groups'])}｜宿主 {m['hosting']}")
    print("  · 方向 1 manifest ↔ 运行时一致 ✓")
    print("  · 行为属性 manifest ↔ 运行时逐项相等 ✓")
    print("  · 输出结构 declared/undeclared ↔ 运行时一致 ✓")
    print("  · 方向 2 消费侧闭合 " + ("✓（已校验）" if args.consumers else "·（无消费侧，跳过）"))
    print("  · 反向自检（摘条目应报错）✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
