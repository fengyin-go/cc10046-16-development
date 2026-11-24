"""采集计划领域服务：按计划归属审核采集来源。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class CollectionPlanService(BaseModuleService):
    MODULE = "collection_plan"
    ENTITY = "采集计划"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["计划标识", "计划名称", "来源站点", "用途", "申请资料范围", "计划状态"]
    REQUIRED_FIELDS = ["计划标识", "来源站点"]
    STATUS_ORDER = ["待审核", "生效中", "已驳回", "已停用"]
    ACTION_RULES = {"批准扩大范围": "生效中", "批准": "生效中", "驳回": "已驳回", "停用计划": "已停用"}
    NEGATIVE_ACTIONS = ["驳回"]

    def run_action(self, entry_id: int, action: str):  # type: ignore[override]
        if action in {"批准扩大范围", "批准", "审批通过"}:
            from app.services.attribution import attribution_service
            result = attribution_service.approve_expansion({"plan_id": entry_id})
            return result.get("plan"), result.get("message") or "扩大范围已批准"
        return super().run_action(entry_id, action)

    @property
    def attribution(self):
        from app.services.attribution import attribution_service
        return attribution_service

    def domain_claim_session(self, *args, **kwargs):
        return self.attribution.claim(*args, **kwargs)

    def __getattr__(self, name: str):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        from app.services.attribution import resolve_dynamic_attr
        fn = resolve_dynamic_attr(name)
        if fn is None:
            raise AttributeError(name)
        return fn
