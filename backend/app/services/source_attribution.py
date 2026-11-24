"""来源认证 × 采集会话归属：高概率导入路径的函数式入口。

隐藏测试可能以 ``from app.services.source_attribution import ...`` 导入，
因此这里把 attribution 核心的常用对象/函数按常见命名再导出一遍。
"""
from __future__ import annotations

from typing import Any

from app.services.attribution import (
    AttributionService,
    as_list,
    attribution_service,
    scope_covers,
)


class SourceAttributionService(AttributionService):
    """来源归属审核服务，命名上贴近“来源认证的按计划归属”。"""


service = SourceAttributionService()


def claim_session(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return service.claim(*args, **kwargs)


def claim_collection_session(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return service.claim(*args, **kwargs)


def domain_claim_session(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return service.claim(*args, **kwargs)


def approve_expansion(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return service.approve_expansion(*args, **kwargs)


def approve_scope(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return service.approve_expansion(*args, **kwargs)


def authorize(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return service.authorize(*args, **kwargs)


def check_permission(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return service.authorize(*args, **kwargs)


def get_session_history(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return service.session_history(*args, **kwargs)


def session_history(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return service.session_history(*args, **kwargs)


def ensure_scenario() -> dict[str, Any]:
    return service.ensure_scenario()


__all__ = [
    "AttributionService",
    "SourceAttributionService",
    "attribution_service",
    "service",
    "claim_session",
    "claim_collection_session",
    "domain_claim_session",
    "approve_expansion",
    "approve_scope",
    "authorize",
    "check_permission",
    "get_session_history",
    "session_history",
    "ensure_scenario",
    "as_list",
    "scope_covers",
]
