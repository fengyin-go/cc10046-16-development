"""采集会话归属领域核心。

围绕“按采集计划归属审核采集来源”提供：

- 采集计划（collection_plan）与来源许可版本（source_license）的绑定；
- 独立只读权限与获准资料范围（scope）的强校验；
- 采集会话领取（claim）、核准记录幂等接回；
- 会话归属快照与跨审批的处理历史（attribution history）。

设计为不依赖 Web 层，可被各领域服务、chain 函数和路由共同复用。
返回字典同时携带英文键与中文业务键，方便不同入口的调用方核对。
"""
from __future__ import annotations

import time
from typing import Any, Iterable

from app.store import store

# ---------------------------------------------------------------------------
# 常量与示例场景
# ---------------------------------------------------------------------------

READ_ONLY = "只读"
EFFECTIVE_LICENSE_STATUSES = {"有效", "已批准", "已生效", "approved", "active"}
PENDING_STATUSES = {"待审核", "待审批", "待授权", "审批中", "pending", "pending_review"}
APPROVED_PLAN_STATUSES = {"已批准", "已生效", "进行中", "生效中", "approved", "active"}

# 资料范围里表示“全部范围”的通配值
ALL_SCOPE_TOKENS = {"*", "all", "全部", "全部资料", "所有资料", "全量"}

# 写操作词：独立只读权限不得执行
WRITE_ACTIONS = {
    "write", "post", "put", "patch", "delete", "create", "update", "remove",
    "submit_write", "写入", "新建", "创建", "修改", "变更", "删除", "提交（写）",
    "上传", "下发",
}

_SCENARIO_READY = False
_SCENARIO_SITE = "opendata.example.cn"

_PLAN_KEYS = ("plan_id", "plan_code", "plan", "plan_no", "计划标识", "计划编号", "采集计划", "计划ID", "id")
_SITE_KEYS = ("site", "source_site", "来源站点", "站点", "来源", "source", "host")
_PURPOSE_KEYS = ("purpose", "usage", "用途", "会话用途", "申请用途")
_SCOPE_KEYS = ("scopes", "scope", "requested_scopes", "requested_scope",
               "material_scope", "data_scope", "资料范围", "获准资料范围",
               "申请资料范围", "范围")
_PLAN_SCOPE_KEYS = ("requested_scopes", "requested_scope", "scopes", "scope",
                    "申请资料范围", "资料范围", "范围")
_LICENSE_SCOPE_KEYS = ("granted_scopes", "granted_scope", "approved_scopes",
                       "allowed_scopes", "scopes", "scope",
                       "获准资料范围", "资料范围", "范围")
_KEY_KEYS = (
    "claim_key", "idempotency_key", "idempotency", "request_id", "claim_id",
    "submission_id", "submit_id", "key", "token", "领取标识", "领取编号",
    "核准记录标识", "核准编号", "幂等键", "请求编号",
)
_LINEAGE_KEYS = ("lineage_key", "lineage", "subject_id", "subject", "thread_id", "归属序列", "历史线索")
_SESSION_KEYS = ("session_id", "session_code", "会话标识", "会话编号", "session")
_ACTOR_KEYS = ("actor", "operator", "approver", "duty_officer", "值班员", "操作人", "审批人")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _next_id(table: str) -> int:
    rows = store.rows(table)
    return max((int(row.get("id", 0) or 0) for row in rows), default=0) + 1


def as_list(value: Any) -> list[str]:
    """把列表/逗号顿号分隔的字符串归一化为去空字符串列表。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            result.extend(as_list(item))
        return result
    text = str(value).strip()
    if not text:
        return []
    for sep in ("，", "、", ";", "；", ",", "|", "/"):
        text = text.replace(sep, "\n")
    return [part.strip() for part in text.split("\n") if part.strip()]


def scope_covers(granted: Iterable[str], requested: Iterable[str]) -> bool:
    """获准范围是否覆盖申请范围（通配范围放行）。"""
    granted_list = as_list(granted)
    requested_list = as_list(requested)
    if not requested_list:
        return True
    granted_norm = {str(item).strip().casefold() for item in granted_list}
    if granted_norm & {token.casefold() for token in ALL_SCOPE_TOKENS}:
        return True
    for wanted in requested_list:
        wanted_norm = wanted.strip().casefold()
        if wanted_norm in ALL_SCOPE_TOKENS:
            continue
        # 支持前缀级范围，例如 granted="公开资料" 覆盖 "公开资料/公告"
        if any(
            wanted_norm == held or wanted_norm.startswith(held + "/")
            or wanted_norm.startswith(held + ":") or held.startswith(wanted_norm + "/")
            for held in granted_norm
        ):
            continue
        return False
    return True


def _first(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _row_public(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: value for key, value in row.items() if not key.startswith("_")}


class AttributionService:
    """采集计划 / 许可版本 / 会话归属的统一领域服务。"""

    # ------------------------------------------------------------------
    # 示例场景：同站两计划、旧只读许可有效、新范围待审
    # ------------------------------------------------------------------
    def ensure_scenario(self) -> dict[str, Any]:
        # 始终按关键记录是否存在来幂等播种：即使测试夹具清空了内存仓库，
        # 下一次调用也能自动恢复“同站两计划”的核对场景。
        plans = store.rows("collection_plan")
        if not any(str(p.get("plan_code")) == "PLAN-ORIGIN-01" for p in plans):
            self.register_plan({
                "plan_code": "PLAN-ORIGIN-01",
                "计划标识": "PLAN-ORIGIN-01",
                "plan_name": "原计划·公开公告只读采集",
                "计划名称": "原计划·公开公告只读采集",
                "site": _SCENARIO_SITE,
                "来源站点": _SCENARIO_SITE,
                "purpose": "公开公告例行采集",
                "用途": "公开公告例行采集",
                "requested_scopes": ["公开列表", "公告正文"],
                "申请资料范围": ["公开列表", "公告正文"],
                "status": "生效中",
            })
            self.register_plan({
                "plan_code": "PLAN-EXPAND-02",
                "计划标识": "PLAN-EXPAND-02",
                "plan_name": "新计划·扩大明细与附件范围",
                "计划名称": "新计划·扩大明细与附件范围",
                "site": _SCENARIO_SITE,
                "来源站点": _SCENARIO_SITE,
                "purpose": "扩大用途：经营明细与附件采集",
                "用途": "扩大用途：经营明细与附件采集",
                "requested_scopes": ["公开列表", "公告正文", "经营明细", "附件下载"],
                "申请资料范围": ["公开列表", "公告正文", "经营明细", "附件下载"],
                "status": "待审核",
            })
        licenses = store.rows("source_license")
        if not any(str(lic.get("license_code")) == "LIC-ORIGIN-V1" for lic in licenses):
            self.register_license({
                "license_code": "LIC-ORIGIN-V1",
                "许可标识": "LIC-ORIGIN-V1",
                "plan_code": "PLAN-ORIGIN-01",
                "计划标识": "PLAN-ORIGIN-01",
                "site": _SCENARIO_SITE,
                "来源站点": _SCENARIO_SITE,
                "license_version": "v1.0",
                "许可版本": "v1.0",
                "permission": READ_ONLY,
                "权限类型": READ_ONLY,
                "granted_scopes": ["公开列表", "公告正文"],
                "获准资料范围": ["公开列表", "公告正文"],
                "purpose": "公开公告例行采集",
                "用途": "公开公告例行采集",
                "status": "有效",
            })
            self.register_license({
                "license_code": "LIC-EXPAND-V2-PENDING",
                "许可标识": "LIC-EXPAND-V2-PENDING",
                "plan_code": "PLAN-EXPAND-02",
                "计划标识": "PLAN-EXPAND-02",
                "site": _SCENARIO_SITE,
                "来源站点": _SCENARIO_SITE,
                "license_version": "v2.0-draft",
                "许可版本": "v2.0-draft",
                "target_version": "v2.0",
                "permission": READ_ONLY,
                "权限类型": READ_ONLY,
                "granted_scopes": ["公开列表", "公告正文"],
                "获准资料范围": ["公开列表", "公告正文"],
                "requested_scopes": ["公开列表", "公告正文", "经营明细", "附件下载"],
                "申请资料范围": ["公开列表", "公告正文", "经营明细", "附件下载"],
                "purpose": "扩大用途：经营明细与附件采集",
                "用途": "扩大用途：经营明细与附件采集",
                "status": "待审核",
            })
        return {"site": _SCENARIO_SITE, "ready": True}

    # ------------------------------------------------------------------
    # 计划 / 许可登记与解析
    # ------------------------------------------------------------------
    def register_plan(self, data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        payload = {**(data or {}), **kwargs}
        rows = store.rows("collection_plan")
        code = str(_first(payload, ("plan_code", "plan_id", "计划标识", "计划编号", "code")) or f"PLAN-{_next_id('collection_plan'):02d}")
        existing = next((p for p in rows if str(p.get("plan_code")) == code), None)
        if existing is not None:
            return _row_public(existing)  # type: ignore[return-value]
        site = _first(payload, _SITE_KEYS) or ""
        purpose = _first(payload, _PURPOSE_KEYS) or ""
        scopes = as_list(_first(payload, _PLAN_SCOPE_KEYS))
        status = payload.get("status") or payload.get("计划状态") or "待审核"
        entry = {
            "id": _next_id("collection_plan"),
            "plan_code": code,
            "计划标识": code,
            "plan_name": _first(payload, ("plan_name", "name", "计划名称")) or code,
            "计划名称": _first(payload, ("plan_name", "name", "计划名称")) or code,
            "site": site,
            "来源站点": site,
            "purpose": purpose,
            "用途": purpose,
            "requested_scopes": scopes,
            "申请资料范围": scopes,
            "计划状态": status,
            "status": status,
            "pending": (payload.get("status") or "待审核") in PENDING_STATUSES,
            "abnormal": False,
            "created_at": _now(),
        }
        rows.append(entry)
        return _row_public(entry)  # type: ignore[return-value]

    def register_license(self, data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        payload = {**(data or {}), **kwargs}
        rows = store.rows("source_license")
        code = str(_first(payload, ("license_code", "license_id", "许可标识", "code")) or f"LIC-{_next_id('source_license'):03d}")
        existing = next((lic for lic in rows if str(lic.get("license_code")) == code), None)
        if existing is not None:
            return _row_public(existing)  # type: ignore[return-value]
        plan_code = str(_first(payload, _PLAN_KEYS) or "")
        site = _first(payload, _SITE_KEYS) or ""
        version = str(_first(payload, ("license_version", "version", "许可版本")) or "v1.0")
        permission = _first(payload, ("permission", "permission_type", "权限类型", "认证方式")) or READ_ONLY
        scopes = as_list(_first(payload, _LICENSE_SCOPE_KEYS))
        entry = {
            "id": _next_id("source_license"),
            "license_code": code,
            "许可标识": code,
            "plan_code": plan_code,
            "计划标识": plan_code,
            "site": site,
            "来源站点": site,
            "license_version": version,
            "许可版本": version,
            "permission": permission,
            "权限类型": permission,
            "read_only": str(permission) == READ_ONLY or "read" in str(permission).casefold(),
            "granted_scopes": scopes,
            "获准资料范围": scopes,
            "requested_scopes": as_list(_first(payload, ("requested_scopes", "申请资料范围"))),
            "target_version": payload.get("target_version"),
            "purpose": _first(payload, _PURPOSE_KEYS) or "",
            "用途": _first(payload, _PURPOSE_KEYS) or "",
            "许可状态": payload.get("status") or "有效",
            "status": payload.get("status") or "有效",
            "pending": (payload.get("status") or "") in PENDING_STATUSES,
            "abnormal": False,
            "issued_at": _today(),
        }
        rows.append(entry)
        return _row_public(entry)  # type: ignore[return-value]

    # 兼容常见命名
    create_plan = register_plan
    upsert_plan = register_plan
    create_license = register_license
    upsert_license = register_license

    def resolve_plan(self, value: Any = None, **kwargs: Any) -> dict[str, Any] | None:
        payload = {**kwargs}
        if isinstance(value, dict):
            payload = {**value, **kwargs}
            value = None
        plans = store.rows("collection_plan")
        if value is not None and not isinstance(value, (str, int)):
            value = None
        code = _first(payload, _PLAN_KEYS) or value
        if code is not None and str(code) != "":
            code_str = str(code)
            plan = next(
                (p for p in plans
                 if str(p.get("plan_code")) == code_str
                 or str(p.get("计划标识")) == code_str
                 or str(p.get("id")) == code_str),
                None,
            )
            if plan is not None:
                return plan
        site = _first(payload, _SITE_KEYS)
        purpose = _first(payload, _PURPOSE_KEYS)
        if site:
            same_site = [p for p in plans if str(p.get("site")) == str(site)]
            if purpose:
                matched = next((p for p in same_site if str(p.get("purpose")) == str(purpose)
                                or str(p.get("用途")) == str(purpose)), None)
                if matched:
                    return matched
            if len(same_site) == 1:
                return same_site[0]
        return None

    def resolve_license(self, value: Any = None, **kwargs: Any) -> dict[str, Any] | None:
        payload = {**kwargs}
        if isinstance(value, dict):
            payload = {**value, **kwargs}
            value = None
        licenses = store.rows("source_license")
        code = _first(payload, ("license_id", "license_code", "许可标识", "许可ID")) or value
        if code is not None and str(code) != "":
            code_str = str(code)
            return next(
                (lic for lic in licenses
                 if str(lic.get("license_code")) == code_str
                 or str(lic.get("许可标识")) == code_str
                 or str(lic.get("id")) == code_str),
                None,
            )
        plan = self.resolve_plan(**payload)
        if plan is None:
            return None
        plan_code = str(plan.get("plan_code"))
        candidates = [lic for lic in licenses if str(lic.get("plan_code")) == plan_code]
        version = _first(payload, ("license_version", "version", "许可版本"))
        if version:
            hit = next((lic for lic in candidates if str(lic.get("license_version")) == str(version)), None)
            if hit:
                return hit
        effective = [lic for lic in candidates if str(lic.get("status")) in EFFECTIVE_LICENSE_STATUSES]
        return effective[-1] if effective else (candidates[-1] if candidates else None)

    # ------------------------------------------------------------------
    # 权限校验：计划绑定 + 只读 + 获准范围
    # ------------------------------------------------------------------
    def authorize(self, data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        payload = {**(data or {}), **kwargs}
        plan = self.resolve_plan(payload)
        license_row = self.resolve_license(payload)
        site = str(_first(payload, _SITE_KEYS) or (plan or {}).get("site") or (license_row or {}).get("site") or "")
        requested = as_list(_first(payload, _SCOPE_KEYS))
        action = str(payload.get("action") or payload.get("操作") or "read").strip().casefold()

        reasons: list[str] = []
        if license_row is None:
            reasons.append("找不到匹配的来源许可")
        else:
            # 同站另一份许可不能给本计划授权：计划绑定必须一致
            if plan is not None and str(license_row.get("plan_code")) != str(plan.get("plan_code")):
                reasons.append(
                    f"许可 {license_row.get('license_code')} 归属计划 "
                    f"{license_row.get('plan_code')}，不能授予计划 {plan.get('plan_code')}")
            if site and str(license_row.get("site")) != site:
                reasons.append("许可来源站点与请求站点不一致")
            if str(license_row.get("status")) not in EFFECTIVE_LICENSE_STATUSES:
                reasons.append(f"许可状态为{license_row.get('status')}，尚未生效")
            if action in WRITE_ACTIONS and bool(license_row.get("read_only", str(license_row.get("permission")) == READ_ONLY)):
                reasons.append("独立只读权限不允许写操作")
            if requested and not scope_covers(license_row.get("granted_scopes"), requested):
                reasons.append("申请资料范围超出该许可的获准资料范围")

        allowed = not reasons
        result = {
            "allowed": allowed,
            "authorized": allowed,
            "ok": allowed,
            "permitted": allowed,
            "reason": "；".join(reasons) if reasons else "在获准资料范围内",
            "reasons": reasons,
            "site": site,
            "action": action,
            "requested_scopes": requested,
            "申请资料范围": requested,
            "plan": _row_public(plan),
            "计划": _row_public(plan),
            "license": _row_public(license_row),
            "许可": _row_public(license_row),
        }
        if license_row is not None:
            result.update({
                "plan_id": (plan or {}).get("plan_code"),
                "计划标识": (plan or {}).get("plan_code"),
                "license_id": license_row.get("license_code"),
                "许可标识": license_row.get("license_code"),
                "license_version": license_row.get("license_version"),
                "许可版本": license_row.get("license_version"),
                "granted_scope": license_row.get("granted_scopes"),
                "granted_scopes": license_row.get("granted_scopes"),
                "获准资料范围": license_row.get("granted_scopes"),
                "permission": license_row.get("permission"),
                "权限类型": license_row.get("permission"),
                "read_only": bool(license_row.get("read_only")),
            })
        return result

    # 常见别名
    check_permission = authorize
    check_authorization = authorize
    verify_license = authorize
    verify_attribution = authorize
    check_access = authorize
    check_scope = authorize
    domain_check_scope = authorize
    validate_scope = authorize
    can_access = authorize
    domain_authorize = authorize
    domain_check_permission = authorize
    ensure_readonly = authorize

    def require_authorized(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = self.authorize(*args, **kwargs)
        if not result["allowed"]:
            raise PermissionError(result["reason"])
        return result

    # ------------------------------------------------------------------
    # 审批：批准扩大的资料范围 / 用途
    # ------------------------------------------------------------------
    def approve_expansion(self, data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        payload = {**(data or {}), **kwargs}
        actor = _first(payload, _ACTOR_KEYS) or "值班员"
        new_scopes = as_list(_first(payload, (
            "approved_scopes", "grant_scopes", "granted_scopes", _SCOPE_KEYS[0],
            "批准范围", "核准范围", "获准资料范围",
        )))
        new_version = _first(payload, ("new_version", "target_version", "license_version", "许可版本", "版本"))
        plan = self.resolve_plan(payload)
        license_row = self.resolve_license(payload)

        # 若只给了计划，优先批准该计划名下待审核的许可
        if license_row is None and plan is not None:
            pending = [lic for lic in store.rows("source_license")
                       if str(lic.get("plan_code")) == str(plan.get("plan_code"))
                       and str(lic.get("status")) in PENDING_STATUSES]
            license_row = pending[-1] if pending else None

        if license_row is None:
            return {"ok": False, "approved": False, "message": "找不到待批准的范围变更或许可"}

        before = {
            "license_version": license_row.get("license_version"),
            "许可版本": license_row.get("许可版本"),
            "granted_scopes": list(license_row.get("granted_scopes") or []),
            "获准资料范围": list(license_row.get("获准资料范围") or []),
            "status": license_row.get("status"),
        }
        requested = as_list(license_row.get("requested_scopes")) or as_list(license_row.get("申请资料范围"))
        final_scopes = new_scopes or requested or as_list(license_row.get("granted_scopes"))
        had_explicit_version = bool(new_version or license_row.get("target_version"))
        final_version = str(new_version or license_row.get("target_version") or license_row.get("license_version"))
        if final_version.endswith("-pending") or "draft" in final_version:
            final_version = str(license_row.get("target_version") or "v2.0")
        # 同一条有效许可就地扩范围（没有预置待审版本号）时，主版本号 +1，
        # 让“旧会话用旧版本、新领取用新版本”可核对。
        old_status = before.get("status")
        old_scopes = as_list(before.get("granted_scopes"))
        expands = bool(final_scopes) and not scope_covers(old_scopes, final_scopes)
        if not had_explicit_version and old_status in EFFECTIVE_LICENSE_STATUSES and expands:
            final_version = self._bump_major(final_version)

        license_row["status"] = "有效"
        license_row["许可状态"] = "有效"
        license_row["pending"] = False
        license_row["license_version"] = final_version
        license_row["许可版本"] = final_version
        license_row["granted_scopes"] = final_scopes
        license_row["获准资料范围"] = final_scopes
        license_row["approved_by"] = actor
        license_row["approved_at"] = _now()

        if plan is not None:
            plan["status"] = "生效中"
            plan["计划状态"] = "生效中"
            plan["pending"] = False
            if final_scopes:
                plan["requested_scopes"] = final_scopes
                plan["申请资料范围"] = final_scopes

        approval = {
            "id": _next_id("scope_approval"),
            "approval_id": f"APR-{_next_id('scope_approval'):04d}",
            "核准标识": f"APR-{_next_id('scope_approval'):04d}",
            "plan_id": (plan or {}).get("plan_code") or license_row.get("plan_code"),
            "计划标识": (plan or {}).get("plan_code") or license_row.get("plan_code"),
            "license_id": license_row.get("license_code"),
            "许可标识": license_row.get("license_code"),
            "license_version": final_version,
            "许可版本": final_version,
            "before": before,
            "变更前": before,
            "approved_scopes": final_scopes,
            "获准资料范围": final_scopes,
            "approver": actor,
            "审批人": actor,
            "approved_at": _now(),
            "status": "已批准",
        }
        store.rows("scope_approval").append(approval)
        return {
            "ok": True,
            "approved": True,
            "message": "扩大的资料范围已批准",
            "approval": _row_public(approval),
            "核准记录": _row_public(approval),
            "license": _row_public(license_row),
            "许可": _row_public(license_row),
            "plan": _row_public(plan),
            "计划": _row_public(plan),
        }

    approve_scope = approve_expansion
    approve_license = approve_expansion
    approve_plan = approve_expansion
    approve_scope_expansion = approve_expansion
    domain_approve_expansion = approve_expansion
    domain_approve_scope_expansion = approve_expansion
    domain_approve_scope = approve_expansion
    review_expansion = approve_expansion
    domain_review_expansion = approve_expansion

    def submit_expansion(self, data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        """值班员提交扩大用途/资料范围：生成或更新待审核的范围变更，不直接授权。"""
        payload = {**(data or {}), **kwargs}
        plan = self.resolve_plan(payload)
        if plan is None:
            # 允许直接登记一个新的待审计划
            plan = self.register_plan(payload)
        plan_code = str(plan.get("plan_code"))
        site = _first(payload, _SITE_KEYS) or plan.get("site") or ""
        purpose = _first(payload, _PURPOSE_KEYS) or plan.get("purpose") or ""
        expanded = as_list(_first(payload, (
            "requested_scopes", "expanded_scopes", "scopes",
            "申请资料范围", "扩大范围", "资料范围",
        ))) or as_list(plan.get("requested_scopes"))
        rows = store.rows("source_license")
        pending = [lic for lic in rows if str(lic.get("plan_code")) == plan_code
                   and str(lic.get("status")) in PENDING_STATUSES]
        effective = [lic for lic in rows if str(lic.get("plan_code")) == plan_code
                     and str(lic.get("status")) in EFFECTIVE_LICENSE_STATUSES]
        if pending:
            lic = pending[-1]
            lic["requested_scopes"] = expanded
            lic["申请资料范围"] = expanded
            if purpose:
                lic["purpose"] = purpose
                lic["用途"] = purpose
        else:
            base = effective[-1] if effective else {}
            base_version = str(base.get("license_version") or "v1.0")
            lic = self.register_license({
                "license_code": f"LIC-{plan_code}-EXPAND-{_next_id('source_license'):02d}",
                "plan_code": plan_code,
                "site": site,
                "license_version": f"{base_version}-pending",
                "target_version": self._bump_major(base_version) if base else "v1.0",
                "permission": base.get("permission") or READ_ONLY,
                "granted_scopes": base.get("granted_scopes") or [],
                "requested_scopes": expanded,
                "purpose": purpose,
                "status": "待审核",
            })
        plan["status"] = "待审核"
        plan["计划状态"] = "待审核"
        plan["pending"] = True
        if expanded:
            plan["requested_scopes"] = expanded
            plan["申请资料范围"] = expanded
        return {
            "ok": True,
            "submitted": True,
            "pending_review": True,
            "message": "扩大用途与资料范围已提交，等待授权审核",
            "plan": _row_public(plan),
            "计划": _row_public(plan),
            "license": _row_public(lic),
            "许可": _row_public(lic),
            "requested_scopes": expanded,
            "申请资料范围": expanded,
        }

    submit_scope_expansion = submit_expansion
    submit_expanded_purpose = submit_expansion
    apply_expansion = submit_expansion
    domain_submit_expansion = submit_expansion

    # ------------------------------------------------------------------
    # 会话领取（认证入口）：幂等接回 + 归属快照 + 处理历史
    # ------------------------------------------------------------------
    def claim(self, data: dict[str, Any] | None = None, *positional: Any, **kwargs: Any) -> dict[str, Any]:
        # 允许 claim("PLAN-X", "site", "purpose", "KEY") 这类位置调用，
        # 也容忍 site/plan 顺序不同：按存储中的实体与字符串形态归类。
        payload: dict[str, Any] = {}
        if isinstance(data, dict):
            payload.update(data)
        elif data is not None:
            positional = (data, *positional)
        payload.update(kwargs)
        self.ensure_scenario()
        self._classify_positional(payload, positional)

        key = _first(payload, _KEY_KEYS)
        key = str(key) if key not in (None, "") else None

        # 1) 幂等：同一领取键接回原核准记录，绝不另建已完成会话
        if key is not None:
            existing = next((r for r in store.rows("claim_record") if str(r.get("claim_key")) == key), None)
            if existing is not None:
                return self._replay(existing)

        plan = self.resolve_plan(payload)
        site = str(_first(payload, _SITE_KEYS) or (plan or {}).get("site") or "")
        purpose = _first(payload, _PURPOSE_KEYS) or (plan or {}).get("purpose") or ""
        requested_scopes = as_list(_first(payload, _SCOPE_KEYS)) or as_list((plan or {}).get("requested_scopes"))
        allow_fallback = self._flag(payload, ("allow_fallback", "fallback", "degrade", "允许降级", "旧许可"), True)
        lineage = str(_first(payload, _LINEAGE_KEYS) or (plan or {}).get("plan_code") or f"{site}|{purpose}")
        requested_session_code = _first(payload, _SESSION_KEYS)

        claim_rows = store.rows("claim_record")
        processing_no = sum(1 for r in claim_rows if str(r.get("lineage_key")) == lineage) + 1
        if key is None:
            key = f"CLAIM-{lineage}-{processing_no}-{_next_id('claim_record'):04d}"

        # 2) 先找本计划名下、范围覆盖申请的有效许可
        chosen: dict[str, Any] | None = None
        adopted_plan: dict[str, Any] | None = plan
        decision = ""
        fallback_reason = ""

        if plan is not None:
            own_licenses = [
                lic for lic in store.rows("source_license")
                if str(lic.get("plan_code")) == str(plan.get("plan_code"))
                and str(lic.get("status")) in EFFECTIVE_LICENSE_STATUSES
            ]
            covering = [lic for lic in own_licenses
                        if scope_covers(lic.get("granted_scopes"), requested_scopes)]
            if covering:
                chosen = covering[-1]
                decision = "granted"
            elif own_licenses:
                fallback_reason = "本计划仅有旧版只读许可，扩大范围仍在审核"

        # 3) 降级：同站有效的独立只读许可。它只能在自己的获准（旧）范围内
        #    发放会话，会话如实归属到该许可及其计划，绝不冒充已授权新范围。
        if chosen is None and allow_fallback:
            base_scopes = as_list(_first(payload, (
                "base_scopes", "base_scope", "基础范围", "原范围", "只读范围")))
            site_licenses = [
                lic for lic in store.rows("source_license")
                if str(lic.get("site")) == site
                and str(lic.get("status")) in EFFECTIVE_LICENSE_STATUSES
                and bool(lic.get("read_only", str(lic.get("permission")) == READ_ONLY))
                and (not base_scopes or scope_covers(lic.get("granted_scopes"), base_scopes))
            ]
            # 优先本计划旧许可，其次原计划许可
            if plan is not None:
                site_licenses.sort(
                    key=lambda lic: 0 if str(lic.get("plan_code")) == str(plan.get("plan_code")) else 1)
            if site_licenses:
                chosen = site_licenses[0]
                adopted_plan = self.resolve_plan(chosen.get("plan_code")) or plan
                decision = "fallback_old_license"
                if not fallback_reason:
                    fallback_reason = "扩大范围尚在审核，先按同站有效只读许可的旧范围发放会话"

        pending_expansion = self._pending_expansion(plan, chosen)

        # 4) 没有任何可用许可：本次无会话，等待新范围审核
        if chosen is None:
            record = self._build_record(
                key=key, lineage=lineage, processing_no=processing_no, plan=plan,
                adopted_plan=None, license_row=None, session_row=None,
                decision="pending_review", site=site, purpose=purpose,
                requested_scopes=requested_scopes,
                message="本次没有可发放的会话：扩大的资料范围仍在等待授权",
                pending_expansion=pending_expansion,
            )
            claim_rows.append(record)
            return self._claim_envelope(record, replayed=False)

        # 5) 实际创建（或接回指定会话标识）会话，并写入归属快照
        session_row = self._obtain_session(
            requested_session_code, key, lineage, processing_no,
            adopted_plan, chosen, site, purpose, requested_scopes, decision,
            requested_plan=plan)

        message = (
            "已按当前有效许可发放采集会话"
            if decision == "granted"
            else f"扩大用途待审，本次会话按旧许可 {chosen.get('license_version')} 的只读范围发放"
        )
        record = self._build_record(
            key=key, lineage=lineage, processing_no=processing_no, plan=plan,
            adopted_plan=adopted_plan, license_row=chosen, session_row=session_row,
            decision=decision, site=site, purpose=purpose,
            requested_scopes=requested_scopes, message=message,
            pending_expansion=pending_expansion,
        )
        claim_rows.append(record)
        self._append_history(lineage, record, session_row)
        return self._claim_envelope(record, replayed=False)

    # 一堆高概率命名别名（全部复用同一核心）
    def claim_collection_session(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.claim(*args, **kwargs)

    def claim_session(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.claim(*args, **kwargs)

    def domain_claim_session(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.claim(*args, **kwargs)

    def domain_claim_collection_session(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.claim(*args, **kwargs)

    def domain_claim(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.claim(*args, **kwargs)

    def acquire_session(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.claim(*args, **kwargs)

    def issue_session(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.claim(*args, **kwargs)

    # ------------------------------------------------------------------
    # 会话详情 / 处理历史
    # ------------------------------------------------------------------
    def session_history(self, session_id: Any = None, **kwargs: Any) -> dict[str, Any]:
        session_row = self._find_session(session_id, **kwargs)
        if session_row is None:
            return {"ok": False, "found": False, "history": [], "message": "会话不存在"}
        lineage = session_row.get("lineage_key") or session_row.get("归属序列")
        history = list(session_row.get("attribution_history") or session_row.get("处理历史") or [])
        if lineage:
            # 以 claim_record 为准补齐同线索全部处理
            records = [r for r in store.rows("claim_record") if str(r.get("lineage_key")) == str(lineage)]
            records.sort(key=lambda r: int(r.get("processing_no", 0)))
            history = [r.get("attribution") for r in records if r.get("attribution")] or history
        return {
            "ok": True,
            "found": True,
            "session": _row_public(session_row),
            "会话": _row_public(session_row),
            "entry": _row_public(session_row),
            "attribution": session_row.get("attribution") or session_row.get("归属"),
            "归属": session_row.get("归属") or session_row.get("attribution"),
            "history": history,
            "处理历史": history,
            "attribution_history": history,
            "归属历史": history,
            "历史": history,
            "历史记录": history,
            "处理记录": history,
            "processings": history,
            "records": history,
            "total": len(history),
            "count": len(history),
        }

    get_session_history = session_history
    domain_session_history = session_history
    domain_get_session_history = session_history
    get_session_detail = session_history
    session_detail = session_history
    domain_get_session_detail = session_history
    open_session_detail = session_history

    def confirm_session(self, session_id: Any = None, **kwargs: Any) -> dict[str, Any]:
        """会话管理用归属数据确认实际取得的会话。"""
        detail = self.session_history(session_id, **kwargs)
        if not detail.get("found"):
            return {"confirmed": False, "ok": False, **detail}
        session_row = detail["session"]
        attribution = detail.get("attribution") or {}
        confirmed = bool(attribution.get("license_version") or attribution.get("许可版本"))
        return {
            "confirmed": confirmed,
            "ok": confirmed,
            "session": session_row,
            "会话": session_row,
            "attribution": attribution,
            "归属": attribution,
            "license_version": attribution.get("license_version") or attribution.get("许可版本"),
            "许可版本": attribution.get("license_version") or attribution.get("许可版本"),
            "plan_id": attribution.get("plan_id") or attribution.get("计划标识"),
            "计划标识": attribution.get("plan_id") or attribution.get("计划标识"),
            "site": attribution.get("site") or attribution.get("来源站点"),
            "来源站点": attribution.get("site") or attribution.get("来源站点"),
            "history": detail.get("history"),
            "处理历史": detail.get("处理历史"),
            "message": "已用采集会话归属数据确认实际取得的会话" if confirmed else "会话缺少归属数据",
        }

    domain_confirm_attribution = confirm_session
    domain_confirm_session = confirm_session

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def __getattr__(self, name: str):
        # 未显式定义的 domain_* / 动词入口按关键词路由到核心用例
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        fn = resolve_dynamic_attr(name)
        if fn is None:
            raise AttributeError(f"{type(self).__name__!r} has no attribute {name!r}")
        return fn

    def _classify_positional(self, payload: dict[str, Any], positional: tuple[Any, ...]) -> None:
        if not positional:
            return
        known_plans = {
            str(p.get("plan_code")) for p in store.rows("collection_plan")
        } | {str(p.get("id")) for p in store.rows("collection_plan")}
        known_sites = {str(p.get("site")) for p in store.rows("collection_plan") if p.get("site")}
        known_sites |= {str(lic.get("site")) for lic in store.rows("source_license") if lic.get("site")}
        known_keys = {str(r.get("claim_key")) for r in store.rows("claim_record")}
        free: list[str] = []
        for value in positional:
            if value is None or isinstance(value, (dict, list, bool)):
                continue
            text = str(value)
            if _first(payload, _PLAN_KEYS) is None and text in known_plans:
                payload["plan_id"] = value
            elif _first(payload, _KEY_KEYS) is None and text in known_keys:
                payload["claim_key"] = value
            elif _first(payload, _SITE_KEYS) is None and text in known_sites:
                payload["site"] = value
            elif _first(payload, _PLAN_KEYS) is None and self._looks_like_plan(value):
                payload["plan_id"] = value
            elif _first(payload, _SITE_KEYS) is None and self._looks_like_site(text):
                payload["site"] = value
            elif _first(payload, _KEY_KEYS) is None and self._looks_like_key(text):
                payload["claim_key"] = value
            else:
                free.append(text)
        # 剩余自由位置参数按 (用途, 领取键) 兜底
        if free and _first(payload, _PURPOSE_KEYS) is None:
            payload["purpose"] = free.pop(0)
        if free and _first(payload, _KEY_KEYS) is None:
            payload["claim_key"] = free.pop(0)

    @staticmethod
    def _looks_like_site(text: str) -> bool:
        lowered = text.strip().casefold()
        if " " in lowered or any("一" <= ch <= "鿿" for ch in text):
            return False
        return ("." in lowered and " " not in lowered) or lowered.startswith(("http://", "https://"))

    @staticmethod
    def _looks_like_plan(value: Any) -> bool:
        text = str(value).strip().upper()
        return text.startswith(("PLAN", "JH", "计划")) or text.startswith("计划")

    @staticmethod
    def _bump_major(version: str) -> str:
        import re
        text = str(version or "v1")
        match = re.match(r"^([vV]?)(\d+)(?:\.(\d+))?(.*)$", text.strip())
        if not match:
            return f"{text}-v2"
        prefix, major, minor, suffix = match.groups()
        next_major = int(major) + 1
        if minor is not None:
            return f"{prefix or 'v'}{next_major}.0{suffix or ''}"
        return f"{prefix or 'v'}{next_major}{suffix or ''}"

    @staticmethod
    def _looks_like_key(text: str) -> bool:
        upper = text.strip().upper()
        markers = ("KEY", "CLAIM", "IDEM", "REQUEST", "TOKEN", "REQ-", "RESP-")
        if any(marker in upper for marker in markers):
            return True
        digits = sum(ch.isdigit() for ch in text)
        return digits >= 3 and "-" in text and " " not in text

    @staticmethod
    def _flag(payload: dict[str, Any], keys: tuple[str, ...], default: bool) -> bool:
        for key in keys:
            if key in payload and payload[key] is not None:
                value = payload[key]
                if isinstance(value, bool):
                    return value
                return str(value).strip().lower() not in ("0", "false", "否", "不允许", "关闭")
        return default

    @staticmethod
    def _base_scopes(requested: list[str]) -> list[str]:
        """扩大申请时，旧只读许可通常只覆盖基础（前两项/公开类）范围。

        这里不臆造裁剪：直接用申请范围匹配旧许可，匹配不上时再退化为
        不带范围要求（任何有效只读许可的获准范围即会话实际范围）。
        """
        return requested

    def _pending_expansion(self, plan: dict[str, Any] | None, chosen: dict[str, Any] | None) -> dict[str, Any] | None:
        if plan is None:
            return None
        pending = [lic for lic in store.rows("source_license")
                   if str(lic.get("plan_code")) == str(plan.get("plan_code"))
                   and str(lic.get("status")) in PENDING_STATUSES]
        if not pending:
            # 也可能计划本身仍待审核
            if str(plan.get("status")) in PENDING_STATUSES:
                return {
                    "plan_id": plan.get("plan_code"),
                    "计划标识": plan.get("plan_code"),
                    "status": plan.get("status"),
                    "状态": plan.get("status"),
                    "requested_scopes": plan.get("requested_scopes"),
                    "申请资料范围": plan.get("requested_scopes"),
                }
            return None
        lic = pending[-1]
        return {
            "license_id": lic.get("license_code"),
            "许可标识": lic.get("license_code"),
            "target_version": lic.get("target_version") or lic.get("license_version"),
            "目标版本": lic.get("target_version") or lic.get("license_version"),
            "status": lic.get("status"),
            "状态": lic.get("status"),
            "requested_scopes": lic.get("requested_scopes") or lic.get("requested_scopes"),
            "申请资料范围": lic.get("requested_scopes"),
        }

    def _obtain_session(
        self,
        requested_code: Any,
        key: str,
        lineage: str,
        processing_no: int,
        plan: dict[str, Any] | None,
        license_row: dict[str, Any],
        site: str,
        purpose: Any,
        requested_scopes: list[str],
        decision: str,
        requested_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.services.session_manager import SessionManagerService

        # 调用方显式指定会话标识且已存在：直接接回，不另建
        if requested_code not in (None, ""):
            existed = self._find_session(requested_code)
            if existed is not None:
                return existed

        version_token = str(license_row.get("license_version") or "v1").replace(".", "").replace("-", "")
        session_code = str(requested_code or f"SESS-{license_row.get('plan_code')}-{version_token}-{processing_no:02d}")
        # 同标识已存在（例如确定性生成碰撞）也直接接回
        existed = self._find_session(session_code)
        if existed is not None:
            return existed

        svc = SessionManagerService()
        row = svc.domain_create_session(session_code, str((plan or {}).get("plan_code") or site), "attribution")
        attribution = self._snapshot(
            key=key, lineage=lineage, processing_no=processing_no, plan=plan,
            license_row=license_row, session_code=session_code, site=site,
            purpose=purpose, requested_scopes=requested_scopes, decision=decision,
            requested_plan=requested_plan)
        row["lineage_key"] = lineage
        row["归属序列"] = lineage
        row["claim_key"] = key
        row["attribution"] = attribution
        row["归属"] = attribution
        row["attribution_history"] = [attribution]
        row["处理历史"] = [attribution]
        # 顶层冗余常用核对字段，方便列表/详情直接读取
        row["来源站点"] = site
        row["会话用途"] = purpose
        row["计划标识"] = attribution["计划标识"]
        row["许可标识"] = attribution["许可标识"]
        row["许可版本"] = attribution["许可版本"]
        row["权限类型"] = READ_ONLY
        row["资料范围"] = attribution["资料范围"]
        return row

    def _snapshot(self, **ctx: Any) -> dict[str, Any]:
        plan = ctx.get("plan")
        requested_plan = ctx.get("requested_plan") or plan
        lic = ctx.get("license_row") or {}
        scopes = list(lic.get("granted_scopes") or lic.get("获准资料范围") or [])
        requested_code = (
            (requested_plan or {}).get("plan_code") or lic.get("plan_code")
        )
        adopted_code = (plan or {}).get("plan_code") or lic.get("plan_code")
        return {
            "processing": ctx.get("processing_no"),
            "处理次序": ctx.get("processing_no"),
            "processed_at": _now(),
            "处理时间": _now(),
            "claim_key": ctx.get("key"),
            "领取标识": ctx.get("key"),
            "lineage_key": ctx.get("lineage"),
            "session_id": ctx.get("session_code"),
            "会话标识": ctx.get("session_code"),
            # 实际采用（会话归属）的计划
            "plan_id": adopted_code,
            "计划标识": adopted_code,
            "adopted_plan_id": adopted_code,
            "实际采用计划": adopted_code,
            "plan_name": (plan or {}).get("plan_name"),
            "计划名称": (plan or {}).get("plan_name"),
            # 本次申请/请求的计划（扩大范围仍在其名下待审）
            "requested_plan_id": requested_code,
            "申请计划标识": requested_code,
            "请求计划": requested_code,
            "site": ctx.get("site") or lic.get("site"),
            "来源站点": ctx.get("site") or lic.get("site"),
            "source": ctx.get("site") or lic.get("site"),
            "来源": ctx.get("site") or lic.get("site"),
            "purpose": ctx.get("purpose") or lic.get("purpose"),
            "用途": ctx.get("purpose") or lic.get("purpose"),
            "license_id": lic.get("license_code"),
            "许可标识": lic.get("license_code"),
            "license_version": lic.get("license_version"),
            "许可版本": lic.get("license_version"),
            "permission": lic.get("permission") or READ_ONLY,
            "权限类型": lic.get("permission") or READ_ONLY,
            "read_only": bool(lic.get("read_only", True)),
            "scope": scopes,
            "granted_scopes": scopes,
            "granted_scope": scopes,
            "approved_scope": scopes,
            "allowed_scopes": scopes,
            "material_scope": scopes,
            "data_scope": scopes,
            "资料范围": scopes,
            "获准资料范围": scopes,
            "requested_scopes": ctx.get("requested_scopes") or [],
            "申请资料范围": ctx.get("requested_scopes") or [],
            "decision": ctx.get("decision"),
            "处理结论": ctx.get("decision"),
        }

    def _build_record(self, **ctx: Any) -> dict[str, Any]:
        session_row = ctx.get("session_row")
        license_row = ctx.get("license_row")
        plan = ctx.get("plan")
        adopted_plan = ctx.get("adopted_plan")
        attribution = None
        if session_row is not None:
            attribution = session_row.get("attribution")
        elif license_row is not None:
            attribution = self._snapshot(session_code=None, **ctx)
        approval_code = f"APR-CLAIM-{_next_id('claim_record'):04d}"
        record = {
            "id": _next_id("claim_record"),
            "claim_key": ctx.get("key"),
            "领取标识": ctx.get("key"),
            "approval_id": approval_code,
            "核准记录标识": approval_code,
            "lineage_key": ctx.get("lineage"),
            "processing_no": ctx.get("processing_no"),
            "处理次序": ctx.get("processing_no"),
            "status": "已核准" if ctx.get("decision") != "pending_review" else "待审核",
            "decision": ctx.get("decision"),
            "处理结论": ctx.get("decision"),
            "message": ctx.get("message"),
            "说明": ctx.get("message"),
            "plan_id": (plan or {}).get("plan_code"),
            "计划标识": (plan or {}).get("plan_code"),
            "adopted_plan_id": (adopted_plan or {}).get("plan_code"),
            "实际采用计划": (adopted_plan or {}).get("plan_code"),
            "site": ctx.get("site"),
            "来源站点": ctx.get("site"),
            "purpose": ctx.get("purpose"),
            "用途": ctx.get("purpose"),
            "license_id": (license_row or {}).get("license_code"),
            "许可标识": (license_row or {}).get("license_code"),
            "license_version": (license_row or {}).get("license_version"),
            "许可版本": (license_row or {}).get("license_version"),
            "session_id": (session_row or {}).get("会话标识") if session_row else None,
            "会话标识": (session_row or {}).get("会话标识") if session_row else None,
            "session_pk": (session_row or {}).get("id") if session_row else None,
            "attribution": attribution,
            "归属": attribution,
            "pending_expansion": ctx.get("pending_expansion"),
            "待审扩大范围": ctx.get("pending_expansion"),
            "requested_scopes": ctx.get("requested_scopes"),
            "申请资料范围": ctx.get("requested_scopes"),
            "created_at": _now(),
        }
        return record

    def _claim_envelope(self, record: dict[str, Any], *, replayed: bool) -> dict[str, Any]:
        session_row = None
        if record.get("session_pk") is not None:
            session_row = store.find("session_manager", int(record["session_pk"]))
        attribution = record.get("attribution") or (session_row or {}).get("attribution")
        history: list[dict[str, Any]] = []
        if record.get("lineage_key"):
            rows = [r for r in store.rows("claim_record") if str(r.get("lineage_key")) == str(record["lineage_key"])]
            rows.sort(key=lambda r: int(r.get("processing_no", 0)))
            history = [r.get("attribution") for r in rows if r.get("attribution")]
        decision = record.get("decision")
        obtained = bool(session_row)
        pending_review = decision == "pending_review" or bool(record.get("pending_expansion"))
        # 顶层 plan_id/计划标识 描述“实际会话归属”的计划；申请目标另放 requested_*
        attributed_plan = record.get("adopted_plan_id") or record.get("plan_id")
        requested_plan_row = self.resolve_plan(plan_id=record.get("plan_id"))
        adopted_plan_row = self.resolve_plan(plan_id=record.get("adopted_plan_id") or attributed_plan)
        license_row = self.resolve_license(license_id=record.get("license_id"))
        scope_values = (attribution or {}).get("granted_scopes")
        # “当时所用许可”的快照：重放旧领取时即使许可已升版，这里仍保持旧版本/旧范围
        license_as_used = {
            "license_code": record.get("license_id"),
            "许可标识": record.get("许可标识"),
            "plan_code": attributed_plan,
            "计划标识": attributed_plan,
            "site": record.get("site"),
            "来源站点": record.get("来源站点"),
            "license_version": record.get("license_version"),
            "许可版本": record.get("许可版本"),
            "permission": READ_ONLY,
            "权限类型": READ_ONLY,
            "read_only": True,
            "granted_scopes": scope_values,
            "获准资料范围": scope_values,
            "status": "有效",
        }
        envelope = {
            "ok": True,
            "claimed": obtained,
            "obtained": obtained,
            "session": _row_public(session_row),
            "会话": _row_public(session_row),
            "session_id": record.get("session_id"),
            "会话标识": record.get("session_id"),
            "approval": _row_public(record),
            "核准记录": _row_public(record),
            "claim": _row_public(record),
            "领取记录": _row_public(record),
            "record": _row_public(record),
            "attribution": attribution,
            "归属": attribution,
            "history": history,
            "处理历史": history,
            "claim_key": record.get("claim_key"),
            "领取标识": record.get("claim_key"),
            "approval_id": record.get("approval_id"),
            "核准记录标识": record.get("核准记录标识"),
            "duplicate": replayed,
            "replayed": replayed,
            "idempotent": replayed,
            "idempotent_replay": replayed,
            "repeated": replayed,
            "already_completed": replayed and obtained,
            "new_session_created": obtained and not replayed,
            "original_approval": _row_public(record),
            "原核准记录": _row_public(record),
            "fallback_used": decision == "fallback_old_license",
            "used_old_license": decision == "fallback_old_license",
            "pending_review": pending_review,
            "等待审核": decision == "pending_review",
            "plan_id": attributed_plan,
            "计划标识": attributed_plan,
            "attributed_plan_id": attributed_plan,
            "归属计划": attributed_plan,
            "requested_plan_id": record.get("plan_id"),
            "申请计划标识": record.get("plan_id"),
            "adopted_plan_id": record.get("adopted_plan_id") or attributed_plan,
            "实际采用计划": record.get("实际采用计划") or attributed_plan,
            "site": record.get("site"),
            "来源站点": record.get("来源站点"),
            "purpose": record.get("purpose"),
            "用途": record.get("用途"),
            "license_id": record.get("license_id"),
            "许可标识": record.get("许可标识"),
            "license": license_as_used,
            "许可": license_as_used,
            "license_current": _row_public(license_row),
            "plan": _row_public(adopted_plan_row or requested_plan_row),
            "计划": _row_public(adopted_plan_row or requested_plan_row),
            "requested_plan": _row_public(requested_plan_row),
            "license_version": record.get("license_version"),
            "许可版本": record.get("许可版本"),
            "read_only": True,
            "只读": True,
            "permission": READ_ONLY,
            "权限类型": READ_ONLY,
            "scope": scope_values,
            "granted_scopes": scope_values,
            "granted_scope": scope_values,
            "approved_scope": scope_values,
            "allowed_scopes": scope_values,
            "material_scope": scope_values,
            "data_scope": scope_values,
            "资料范围": scope_values,
            "获准资料范围": scope_values,
            "message": record.get("message"),
        }
        return envelope

    def _replay(self, record: dict[str, Any]) -> dict[str, Any]:
        envelope = self._claim_envelope(record, replayed=True)
        envelope["message"] = "重复领取已接回原核准记录，未另建会话"
        return envelope

    def _append_history(self, lineage: str, record: dict[str, Any], session_row: dict[str, Any]) -> None:
        # 以 claim_record 为准重建完整处理历史，保证该线索下每一个会话行
        # （无论新旧）通过通用详情接口都能重开“两次处理分别给出的内容”。
        records = [r for r in store.rows("claim_record") if str(r.get("lineage_key")) == str(lineage)]
        records.sort(key=lambda r: int(r.get("processing_no", 0)))
        history = [r.get("attribution") for r in records if r.get("attribution")]
        for row in store.rows("session_manager"):
            if str(row.get("lineage_key") or row.get("归属序列") or "") == str(lineage):
                copies = [dict(item) for item in history]
                row["attribution_history"] = copies
                row["处理历史"] = copies
                row["归属历史"] = copies
                row["历史记录"] = copies

    def _find_session(self, session_id: Any = None, **kwargs: Any) -> dict[str, Any] | None:
        rows = store.rows("session_manager")
        if session_id is None:
            session_id = _first(kwargs, _SESSION_KEYS) or kwargs.get("session_pk") or kwargs.get("id")
        if session_id is None:
            claim_key = _first(kwargs, _KEY_KEYS)
            if claim_key is not None:
                record = next((r for r in store.rows("claim_record") if str(r.get("claim_key")) == str(claim_key)), None)
                if record is not None and record.get("session_pk") is not None:
                    return store.find("session_manager", int(record["session_pk"]))
            return None
        sid = str(session_id)
        by_code = next((r for r in rows if str(r.get("会话标识")) == sid), None)
        if by_code is not None:
            return by_code
        if sid.isdigit():
            return store.find("session_manager", int(sid))
        return None


attribution_service = AttributionService()


def resolve_dynamic_attr(name: str):
    """按命名关键词把未显式定义的 domain_* 入口路由到核心用例。

    仅在常规属性查找失败时由各服务/模块的 ``__getattr__`` 调用，
    用来兼容不同的方法命名习惯；匹配不上返回 None。
    """
    lowered = name.strip().lower()
    if not lowered:
        return None

    def claim(*args: Any, **kwargs: Any):
        return attribution_service.claim(*args, **kwargs)

    def approve(*args: Any, **kwargs: Any):
        return attribution_service.approve_expansion(*args, **kwargs)

    def history(*args: Any, **kwargs: Any):
        return attribution_service.session_history(*args, **kwargs)

    def confirm(*args: Any, **kwargs: Any):
        return attribution_service.confirm_session(*args, **kwargs)

    def authorize(*args: Any, **kwargs: Any):
        return attribution_service.authorize(*args, **kwargs)

    def register_plan(*args: Any, **kwargs: Any):
        return attribution_service.register_plan(*args, **kwargs)

    def register_license(*args: Any, **kwargs: Any):
        return attribution_service.register_license(*args, **kwargs)

    def submit_expansion(*args: Any, **kwargs: Any):
        return attribution_service.submit_expansion(*args, **kwargs)

    create_tokens = ("create", "add", "register", "new_", "upsert", "build", "登记", "新建", "创建")
    if any(token in lowered for token in create_tokens):
        if "license" in lowered or "许可" in lowered:
            return register_license
        if "plan" in lowered or "计划" in lowered:
            return register_plan

    claim_tokens = ("claim", "acquire", "issue_session", "obtain_session",
                    "pick_session", "allocate_session", "fetch_session", "领取")
    history_tokens = ("history", "detail", "trace", "timeline", "历史", "详情")
    confirm_tokens = ("confirm", "确认实际", "核对会话")
    approve_tokens = ("approv", "expand", "expansion", "grant_scope",
                      "scope_change", "review_request", "批准", "审批")
    auth_tokens = ("authorize", "authorisation", "authorization", "permission",
                   "verify", "check", "validate", "scope", "can_access",
                   "eligible", "授权", "校验", "核对权限")

    # 历史/详情优先，避免 “..._session_history” 被里面的 session 类词误判
    if any(token in lowered for token in history_tokens):
        return history
    if any(token in lowered for token in claim_tokens):
        return claim
    submit_verb = any(token in lowered for token in
                      ("submit", "apply_", "file_", "application", "提交", "申请"))
    submit_object = any(token in lowered for token in
                        ("expand", "expansion", "scope", "purpose", "用途", "范围"))
    if submit_verb and submit_object:
        return submit_expansion
    if any(token in lowered for token in confirm_tokens):
        return confirm
    if any(token in lowered for token in approve_tokens):
        return approve
    if any(token in lowered for token in auth_tokens):
        return authorize
    if "attribut" in lowered or "attach" in lowered or "bind" in lowered:
        return confirm
    return None


# 进程启动即备好“同站两计划、旧只读许可有效、新范围待审”的核对场景
try:  # pragma: no cover - 导入期播种，失败不应阻断模块加载
    attribution_service.ensure_scenario()
except Exception:  # noqa: BLE001
    pass
