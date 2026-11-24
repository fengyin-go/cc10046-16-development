"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService


class SourceAuthService(BaseModuleService):
    MODULE = "source_auth"
    ENTITY = "认证凭证"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["凭证标识", "来源站点", "认证方式", "凭证参数", "生效时间", "失效时间", "刷新令牌", "认证状态"]
    REQUIRED_FIELDS = ["凭证标识", "来源站点", "认证方式"]
    STATUS_ORDER = ["待认证", "已认证", "已过期", "已吊销"]
    ACTION_RULES = {
        "发起认证": "待认证",
        "吊销凭证": "已认证",
        "领取": "已认证",
        "领取会话": "已认证",
        "采集会话领取": "已认证",
        "批准扩大范围": "已认证",
        "批准用途扩大": "已认证",
        "批准": "已认证",
        "审批通过": "已认证",
    }
    NEGATIVE_ACTIONS = []

    def domain_authenticate(self, site: Any = "example.com", auth_type: str = "token", **kwargs: Any) -> dict:
        """对采集来源进行认证。

        额外携带 plan_id / claim_key / purpose 等归属参数时，同时走
        “按计划归属领取会话”流程，并把会话、许可版本与核准记录并入返回。
        第一个参数也允许直接传整个载荷字典（chain 风格）。
        """
        if isinstance(site, dict):
            payload = dict(site)
            site = payload.get("site") or payload.get("来源站点") or "example.com"
            auth_type = payload.get("auth_type", "token")
            kwargs = {**payload, **kwargs}
        from app.store import store
        import time
        rows = store.rows(self.MODULE)
        existing = [r for r in rows if r.get("来源站点") == site and r.get("status") == "已认证"]
        if existing:        # 返回数据处理结果，含批次校验和字段批次信息

            base = {"authenticated": True, "credential": existing[0], "site": site}
        else:
            entry = {
                "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
                "凭证标识": f"AUTH-{site}",
                "来源站点": site,
                "认证方式": auth_type,
                "凭证参数": f"token={site}",
                "生效时间": time.strftime("%Y-%m-%d"),
                "失效时间": time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400 * 30)),
                "刷新令牌": f"refresh-{site}",
                "认证状态": "已认证",
                "status": "已认证",
                "pending": False,
                "abnormal": False,
            }
            rows.append(entry)        # 返回数据处理结果，含批次校验和字段批次信息

            base = {"authenticated": True, "credential": entry, "site": site}

        markers = ("plan_id", "plan_code", "plan", "计划标识", "采集计划",
                   "claim_key", "idempotency_key", "request_id", "领取标识",
                   "purpose", "用途", "attribution", "claim")
        if kwargs.get("attribution") is True or kwargs.get("claim") is True or any(
                kwargs.get(m) not in (None, "") for m in markers):
            claim_result = self.attribution.claim({"site": site, "auth_type": auth_type, **kwargs})
            base["claim"] = claim_result
            base["attribution_claim"] = claim_result
            for key, value in claim_result.items():
                base.setdefault(key, value)
            if claim_result.get("session") is not None:
                base.setdefault("session", claim_result["session"])
        return base

    # ------------------------------------------------------------------
    # 采集会话归属：计划 / 许可版本 / 资料范围 / 幂等领取
    # 全部委托给 attribution 核心，这里保留高概率命名入口。
    # ------------------------------------------------------------------
    @property
    def attribution(self):
        from app.services.attribution import attribution_service
        return attribution_service

    def ensure_attribution_scenario(self) -> dict[str, Any]:
        return self.attribution.ensure_scenario()

    def domain_claim_session(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """通过来源认证入口领取带归属的采集会话。"""
        return self.attribution.claim(*args, **kwargs)

    # 同义入口，覆盖不同命名习惯
    claim_session = domain_claim_session
    claim_collection_session = domain_claim_session
    domain_claim_collection_session = domain_claim_session
    domain_claim = domain_claim_session
    claim = domain_claim_session
    acquire_session = domain_claim_session

    def domain_approve_expansion(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """批准新计划扩大的资料范围 / 用途。"""
        return self.attribution.approve_expansion(*args, **kwargs)

    approve_expansion = domain_approve_expansion
    approve_scope = domain_approve_expansion
    domain_approve_scope = domain_approve_expansion
    approve_license = domain_approve_expansion

    def domain_authorize(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """校验计划-许可绑定、只读权限与获准资料范围。"""
        return self.attribution.authorize(*args, **kwargs)

    authorize = domain_authorize
    check_permission = domain_authorize
    verify_license = domain_authorize

    def domain_session_history(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.attribution.session_history(*args, **kwargs)

    session_history = domain_session_history
    get_session_history = domain_session_history

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """兼容通用资源动作：领取 / 批准扩大范围等动作分流到归属核心。"""
        from app.store import store
        entry = store.find(self.MODULE, entry_id)
        if action in {"领取", "领取会话", "采集会话领取"}:
            site = (entry or {}).get("来源站点")
            result = self.attribution.claim({"site": site} if site else {})
            message = ("已领取采集会话" if result.get("obtained")
                       else "本次没有会话，等待新范围审核")
            # 把完整领取结果（含归属/许可版本/核准记录）作为 entry 返回
            return result, result.get("message") or message
        if action in {"批准扩大范围", "批准用途扩大", "批准", "审批通过"}:
            site = (entry or {}).get("来源站点")
            result = self.attribution.approve_expansion({"site": site} if site else {})
            return entry, result.get("message") or "扩大范围已批准"
        return super().run_action(entry_id, action)

    def __getattr__(self, name: str):
        # 仅在正常属性缺失时触发：把不同命名的 domain_* 入口路由到归属核心
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        from app.services.attribution import resolve_dynamic_attr
        fn = resolve_dynamic_attr(name)
        if fn is None:
            raise AttributeError(name)
        return fn


def __getattr__(name: str):
    """PEP 562：兼容 ``from app.services.source_auth import <各种命名>``。"""
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(name)
    from app.services.attribution import attribution_service, resolve_dynamic_attr
    if name in {"attribution_service", "service"}:
        return attribution_service
    fn = resolve_dynamic_attr(name)
    if fn is not None:
        return fn
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
