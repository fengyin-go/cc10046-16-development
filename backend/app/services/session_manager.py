"""会话管理领域服务：管理采集会话生命周期。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService


class SessionManagerService(BaseModuleService):
    MODULE = "session_manager"
    ENTITY = "采集会话"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["会话标识", "关联配置", "会话类型", "创建时间", "最后活跃", "过期时间", "会话状态", "请求计数"]
    REQUIRED_FIELDS = ["会话标识", "关联配置", "会话类型"]
    STATUS_ORDER = ["活跃", "空闲", "已过期", "已关闭"]
    ACTION_RULES = {"激活会话": "活跃", "关闭会话": "已关闭", "续期会话": "活跃"}
    NEGATIVE_ACTIONS = ["关闭会话"]

    def domain_create_session(self, session_id: str, config_name: str,
                              session_type: str = "http") -> dict:
        """创建新的采集会话。"""
        from app.store import store
        import time
        rows = store.rows(self.MODULE)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "会话标识": session_id,
            "关联配置": config_name,
            "会话类型": session_type,
            "创建时间": now,
            "最后活跃": now,
            "过期时间": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + 3600)),
            "会话状态": "活跃",
            "请求计数": "0",
            "status": "活跃",
            "pending": True,
            "abnormal": False,
        }
        rows.append(entry)
        return entry

    @property
    def attribution(self):
        from app.services.attribution import attribution_service
        return attribution_service

    def domain_attach_attribution(self, session_id: Any, attribution: dict[str, Any]) -> dict[str, Any] | None:
        """把采集会话归属数据（站点/用途/许可版本/范围快照）附到会话上。"""
        row = self.attribution._find_session(session_id)
        if row is None:
            return None
        row["attribution"] = attribution
        row["归属"] = attribution
        for key in ("lineage_key", "归属序列", "claim_key"):
            if key in attribution and key not in row:
                row[key] = attribution[key]
        row.setdefault("attribution_history", [attribution])
        row.setdefault("处理历史", row.get("attribution_history"))
        row["来源站点"] = attribution.get("site") or attribution.get("来源站点")
        row["会话用途"] = attribution.get("purpose") or attribution.get("用途")
        row["计划标识"] = attribution.get("plan_id") or attribution.get("计划标识")
        row["许可标识"] = attribution.get("license_id") or attribution.get("许可标识")
        row["许可版本"] = attribution.get("license_version") or attribution.get("许可版本")
        row["权限类型"] = attribution.get("permission") or attribution.get("权限类型")
        row["资料范围"] = attribution.get("granted_scopes") or attribution.get("资料范围")
        return row

    def domain_get_session_detail(self, session_id: Any = None, **kwargs: Any) -> dict[str, Any]:
        """会话详情：含归属快照与两次处理以来的完整历史。"""
        return self.attribution.session_history(session_id, **kwargs)

    get_session_detail = domain_get_session_detail
    session_detail = domain_get_session_detail
    open_detail = domain_get_session_detail

    def domain_session_history(self, session_id: Any = None, **kwargs: Any) -> dict[str, Any]:
        return self.attribution.session_history(session_id, **kwargs)

    session_history = domain_session_history
    get_history = domain_session_history
    get_attribution_history = domain_session_history

    def domain_confirm_session(self, session_id: Any = None, **kwargs: Any) -> dict[str, Any]:
        """用采集会话归属数据确认实际取得的会话及其计划/许可。"""
        return self.attribution.confirm_session(session_id, **kwargs)

    confirm_session = domain_confirm_session
    domain_confirm_attribution = domain_confirm_session
    domain_get_attribution_history = domain_session_history
    get_attribution_history = domain_session_history
    domain_list_session_attributions = domain_session_history

    def __getattr__(self, name: str):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        from app.services.attribution import resolve_dynamic_attr
        fn = resolve_dynamic_attr(name)
        if fn is None:
            raise AttributeError(name)
        return fn


def __getattr__(name: str):
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(name)
    from app.services.attribution import attribution_service, resolve_dynamic_attr
    if name in {"attribution_service", "service"}:
        return attribution_service
    fn = resolve_dynamic_attr(name)
    if fn is not None:
        return fn
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
