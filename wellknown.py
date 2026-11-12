"""线自描述端点 ``/.well-known/line-manifest.json``（change converge-line-identity-and-keys 1.4）。

家族实现：公开、免鉴权、零网络。**原样回吐**本仓 ``line-manifest.json``——仓内那份是
唯一真源，这个端点与注册表的 ``metadata.identity`` 都只是它的投影；这里一旦加工
（解析后再 dump、补字段、排序），就出现第二个真源，两处投影必然漂移。

路径解析是「候选链」而不是一条固定路径，原因在**本仓的布局**：这是一组平铺在仓根的
py-module（``pyproject.toml`` 的 ``py-modules``），``wellknown.py`` 与 ``line-manifest.json``
同目录。所以：

* 源码树里 ``__file__`` 是 ``<repo>/wellknown.py``，``parents[0]`` 就是仓根；
* 镜像里 ``WORKDIR /app`` + ``ENTRYPOINT ["python", "server.py"]``，``__file__`` 是
  ``/app/wellknown.py``，``parents[0]`` 还是仓根（``COPY . .`` 把清单放在 ``/app``）；
* 只有 ``pip install .`` 之后模块落进 site-packages 时 ``__file__`` 才不在仓根——那时
  **CWD** 才是仓根，所以 CWD 排第二。

这就是 **N=0**（模块同级），不是家族模板里的 N=1：本仓没有包目录，``parents[1]`` 是
工作区根 ``finddata/``——下面平铺着上百个兄弟仓。照抄 ``parents[1]`` 会去读邻居的同名
文件，把别人的线身份当成自己的：宁可 404，也不要一个「看起来成功」的错答案。
「包同级」这条兜底在平铺布局下与第一条是同一个位置，已经包含在链首。

两个状态码分得很清：**缺失=404**（该线未发布清单，属配置事实）；**存在但不可解析=500**
（属缺陷，不能伪装成 404 让调用方以为"本来就没有"）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

#: 与 ``fd-info`` / ``wire-ops-mcp`` / ``facet-ops-mcp`` 逐字相同的路径常量。
WELL_KNOWN_PATH = "/.well-known/line-manifest.json"
ENV_MANIFEST_PATH = "LINE_MANIFEST_PATH"
#: 清单是运行期契约：改一次要生效，但不能让边缘缓存长期撒谎。
CACHE_CONTROL = "public, max-age=300"

_CONTENT_TYPE = "application/json; charset=utf-8"


def manifest_candidates() -> list[Path]:
    """按优先级列出可能放清单的位置（``LINE_MANIFEST_PATH`` 一项即封顶）。"""
    override = os.environ.get(ENV_MANIFEST_PATH)
    if override:
        return [Path(override)]
    here = Path(__file__).resolve()
    return [
        here.parent / "line-manifest.json",   # 源码树 / 镜像 /app：模块与清单同根（平铺布局 = 仓根）
        Path.cwd() / "line-manifest.json",    # pip 装进 site-packages：__file__ 不在仓根，CWD 才是
    ]


def manifest_path() -> Path:
    """实际取用的清单路径；都不存在时返回首选位置（让 404 能点名期望路径）。"""
    candidates = manifest_candidates()
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def manifest_response() -> tuple[int, bytes, dict[str, str]]:
    """(status, body, headers) —— 不读网络、不建会话。

    成功时附 ``Cache-Control``，失败时不附：让缓存别把一个"暂时没发布"的 404 记成
    长期事实。
    """
    path = manifest_path()
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return 404, b'{"detail":"line-manifest not published"}', {}
    except OSError as exc:
        detail = f"line-manifest unreadable: {type(exc).__name__}"
        return 500, json.dumps({"detail": detail}).encode(), {}
    try:
        json.loads(raw)
    except ValueError:
        return 500, b'{"detail":"line-manifest is not valid JSON"}', {}
    return 200, raw, {"cache-control": CACHE_CONTROL}


def register(mcp) -> None:
    """把端点挂到 ``FastMCP`` 实例上。

    用 ``custom_route`` 而不是自己包一层 ASGI：路由属于应用本身，于是**两个分支都在**
    ——配了 ``MCP_BEARER_TOKEN`` 时走 ``http_app()``、没配时走 ``run()``，同一份代码。
    鉴权门的豁免在 ``server.py`` 的 ``EXEMPT_PATHS``，两处必须同时改，否则配了令牌的线
    仍然对匿名发现请求回 401。
    """
    if not hasattr(mcp, "custom_route"):  # pragma: no cover - 依赖缺失时宁可起不来
        raise RuntimeError(
            "fastmcp 缺 custom_route：无法挂 " + WELL_KNOWN_PATH + "（升级依赖，别静默跳过）"
        )
    from starlette.responses import Response

    @mcp.custom_route(WELL_KNOWN_PATH, methods=["GET"])
    async def line_manifest(_request):  # noqa: ANN001 - ASGI 边界，不需要类型
        status, body, headers = manifest_response()
        return Response(
            content=body, status_code=status, media_type=_CONTENT_TYPE, headers=headers
        )
