"""会话管理路由的兼容模块：详情/历史/确认入口见 app.routers.attribution。"""
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
