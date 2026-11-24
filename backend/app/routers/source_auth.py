"""来源认证路由的兼容模块。

真正的归属/领取/审批 HTTP 入口集中在 ``app.routers.attribution``；
这里再导出同名 ``router``，并对可能的函数式导入做动态兼容。
"""
from __future__ import annotations

from app.routers.attribution import router  # noqa: F401  (re-export)
from app.services.attribution import attribution_service  # noqa: F401


def __getattr__(name: str):
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(name)
    from app.services.attribution import resolve_dynamic_attr
    if name in {"service", "svc"}:
        return attribution_service
    fn = resolve_dynamic_attr(name)
    if fn is not None:
        return fn
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
