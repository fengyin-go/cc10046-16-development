"""来源许可领域服务：许可绑定计划与许可版本，独立只读权限限定资料范围。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class SourceLicenseService(BaseModuleService):
    MODULE = "source_license"
    ENTITY = "来源许可"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["许可标识", "许可版本", "计划标识", "来源站点", "权限类型", "获准资料范围", "许可状态"]
    REQUIRED_FIELDS = ["许可标识", "计划标识", "来源站点"]
    STATUS_ORDER = ["待审核", "有效", "已驳回", "已吊销"]
    ACTION_RULES = {"批准扩大范围": "有效", "批准": "有效", "吊销许可": "已吊销", "驳回": "已驳回"}
    NEGATIVE_ACTIONS = ["吊销许可", "驳回"]

    def run_action(self, entry_id: int, action: str):  # type: ignore[override]
        if action in {"批准扩大范围", "批准", "审批通过"}:
            from app.services.attribution import attribution_service
            result = attribution_service.approve_expansion({"license_id": entry_id})
            return result.get("license"), result.get("message") or "扩大范围已批准"
        return super().run_action(entry_id, action)

    def domain_check_permission(self, *args, **kwargs):
        from app.services.attribution import attribution_service
        return attribution_service.authorize(*args, **kwargs)

    check_permission = domain_check_permission

    def __getattr__(self, name: str):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        from app.services.attribution import resolve_dynamic_attr
        fn = resolve_dynamic_attr(name)
        if fn is None:
            raise AttributeError(name)
        return fn
