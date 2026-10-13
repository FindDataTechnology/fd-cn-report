"""`catalog.FDcnReportProvider` 契约测试（change cn-report-provider-contract）。

覆盖：
- run() 对全部 9 个声明命令抛**显式 NotImplementedError**（修前实测：悬空
  import `from cnreport_tools import dispatch` 一调即 ImportError）；
- 未知命令同形拒绝；
- 消息含真实替代入口（MCP 工具面提示）；
- 悬空 import 不得复活（cnreport_tools 无 dispatch 属性 + 源码级断言）。

零网络零 LLM：run() 不执行任何抓取。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

# catalog.py 是仓根脚本（非包模块），照 test_catalog_loading 先例加载。
_spec = importlib.util.spec_from_file_location("fd_cn_report_catalog", REPO / "catalog.py")
catalog_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(catalog_mod)

CATALOG = catalog_mod.CATALOG
FDcnReportProvider = catalog_mod.FDcnReportProvider

DECLARED_COMMANDS = [f["command"] for f in CATALOG["functions"]]


def test_catalog_declares_nine_commands():
    """声明清单基线：9 个命令（防清单被无意改动）。"""
    assert len(DECLARED_COMMANDS) == 9


@pytest.mark.parametrize("command", DECLARED_COMMANDS)
def test_declared_commands_raise_explicit_not_implemented(command):
    """每个声明命令抛 NotImplementedError（不是 ImportError），消息含替代入口。"""
    provider = FDcnReportProvider()
    with pytest.raises(NotImplementedError) as excinfo:
        provider.run(command, {})
    message = str(excinfo.value)
    assert "server.py" in message  # 真实入口提示
    assert "list_outline" in message or "extract_section" in message


def test_unknown_command_raises_not_implemented_too():
    """未知命令同形拒绝（显式 NotImplementedError，含命令名）。"""
    provider = FDcnReportProvider()
    with pytest.raises(NotImplementedError) as excinfo:
        provider.run("does_not_exist", {})
    assert "does_not_exist" in str(excinfo.value)


def test_no_dangling_dispatch_import():
    """悬空 import 不得复活：cnreport_tools 无 dispatch 属性（修前目标即此）。"""
    import cnreport_tools

    assert not hasattr(cnreport_tools, "dispatch"), (
        "cnreport_tools.dispatch 不存在；provider 必须显式 NotImplementedError，"
        "不得复活悬空 import"
    )


def test_source_has_no_dispatch_import():
    """源码级断言：catalog.py 不含指向 cnreport_tools 的 dispatch import。"""
    source = (REPO / "catalog.py").read_text(encoding="utf-8")
    assert "import dispatch" not in source
    assert "server_dispatch" not in source


def test_registry_returns_catalog():
    """registry() 仍返回 CATALOG（声明面契约不变）。"""
    assert FDcnReportProvider().registry() is CATALOG
