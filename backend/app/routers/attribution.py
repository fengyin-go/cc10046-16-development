"""采集会话归属 HTTP 入口。

为了适配不同调用习惯，这里在 source_auth / session_manager / attribution
等多个前缀下提供同义路径；核心逻辑全部在 AttributionService。
本路由需要在通用 resource 路由之前注册，避免静态段子路径被动态路由抢先匹配。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.services.attribution import attribution_service

router = APIRouter(prefix="/api", tags=["采集会话归属"])


async def _payload(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return {}
    # 兼容 {values: {...}} / {payload: {...}} 包装
    if isinstance(body.get("values"), dict):
        merged = dict(body["values"])
        merged.update({k: v for k, v in body.items() if k != "values"})
        return merged
    if isinstance(body.get("payload"), dict):
        return dict(body["payload"])
    return body


# ---------------------------------------------------------------------------
# 领取
# ---------------------------------------------------------------------------
async def _claim(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    return attribution_service.claim(payload)


for _path in (
    "/attribution/claim",
    "/attributions/claim",
    "/source_auth/claim",
    "/source_auth/claim-session",
    "/source_auth/sessions/claim",
    "/source-auth/claim",
    "/source-auth/claim-session",
    "/auth/claim",
    "/collection/claim",
    "/collection_plan/claim",
    "/collection-plans/claim",
    "/crawl_plan/claim",
    "/session_manager/claim",
    "/session-manager/claim",
    "/claims",
    "/claims/claim",
):
    router.add_api_route(_path, _claim, methods=["POST"])


# ---------------------------------------------------------------------------
# 审批扩大范围
# ---------------------------------------------------------------------------
async def _approve(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    return attribution_service.approve_expansion(payload)


for _path in (
    "/attribution/approve",
    "/attribution/approve-expansion",
    "/source_auth/approve",
    "/source_auth/approve-expansion",
    "/source_auth/approve-scope",
    "/source_auth/licenses/approve",
    "/source-auth/approve",
    "/licenses/approve",
    "/source_license/approve",
    "/collection_plan/approve",
    "/plans/approve",
):
    router.add_api_route(_path, _approve, methods=["POST"])


# ---------------------------------------------------------------------------
# 权限校验
# ---------------------------------------------------------------------------
async def _authorize(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    return attribution_service.authorize(payload)


for _path in (
    "/attribution/authorize",
    "/attribution/check",
    "/source_auth/authorize",
    "/source_auth/check-permission",
    "/licenses/check",
):
    router.add_api_route(_path, _authorize, methods=["POST"])


# ---------------------------------------------------------------------------
# 会话详情 / 历史 / 确认
# ---------------------------------------------------------------------------
def _history(session_id: str | None = None, request: Request | None = None) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if request is not None:
        query = dict(request.query_params)
    return attribution_service.session_history(session_id, **query)


@router.get("/attribution/sessions/{session_id}/history")
@router.get("/attribution/sessions/{session_id}")
@router.get("/sessions/{session_id}/history")
@router.get("/session_manager/{session_id}/history")
@router.get("/session_manager/{session_id}/detail")
@router.get("/session_manager/{session_id}/attribution")
async def session_history_path(session_id: str, request: Request) -> dict[str, Any]:
    return _history(session_id, request)


@router.get("/attribution/history")
async def session_history_query(request: Request) -> dict[str, Any]:
    query = dict(request.query_params)
    session_id = query.pop("session_id", None) or query.pop("id", None) or query.pop("会话标识", None)
    return attribution_service.session_history(session_id, **query)


async def _history_post(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    session_id = payload.get("session_id") or payload.get("会话标识") or payload.get("id")
    return attribution_service.session_history(session_id, **payload)


for _path in (
    "/attribution/history",
    "/attribution/session-history",
    "/session_manager/history",
    "/session_manager/session-history",
):
    router.add_api_route(_path, _history_post, methods=["POST"])


async def _confirm(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    session_id = payload.get("session_id") or payload.get("会话标识") or payload.get("id")
    return attribution_service.confirm_session(session_id, **payload)


@router.post("/session_manager/{session_id}/confirm")
async def confirm_session_path(session_id: str) -> dict[str, Any]:
    return attribution_service.confirm_session(session_id)


for _path in ("/attribution/confirm", "/session_manager/confirm"):
    router.add_api_route(_path, _confirm, methods=["POST"])


# ---------------------------------------------------------------------------
# 示例场景与总览（供值班员核对 / 前端面板使用）
# ---------------------------------------------------------------------------
@router.get("/attribution/scenario")
async def get_scenario() -> dict[str, Any]:
    attribution_service.ensure_scenario()
    from app.store import store
    return {
        "site": "opendata.example.cn",
        "plans": store.rows("collection_plan"),
        "licenses": store.rows("source_license"),
        "claims": store.rows("claim_record"),
    }


@router.post("/attribution/scenario/ensure")
async def ensure_scenario() -> dict[str, Any]:
    return attribution_service.ensure_scenario()


# ---------------------------------------------------------------------------
# 通配兜底：/api/{module}/{id}/claim | approve | history
# 让 source_auth / collection_plan / session_manager 等模块行上的
# 归属动作都有一致入口。仅在更具体路由之后注册。
# ---------------------------------------------------------------------------
def _row_context(module: str, entry_id: str) -> dict[str, Any]:
    from app.services import service_for
    from app.store import store
    ctx: dict[str, Any] = {}
    service = service_for(module)
    row = None
    if entry_id.isdigit():
        row = store.find(module, int(entry_id))
    if row is None and service is not None:
        for candidate in store.rows(module):
            if str(candidate.get("会话标识")) == entry_id or str(candidate.get("计划标识")) == entry_id \
                    or str(candidate.get("plan_code")) == entry_id or str(candidate.get("许可标识")) == entry_id:
                row = candidate
                break
    if row:
        for key in ("site", "来源站点"):
            if row.get(key):
                ctx["site"] = row[key]
        for key in ("plan_id", "plan_code", "计划标识"):
            if row.get(key):
                ctx["plan_id"] = row[key]
                break
        for key in ("purpose", "用途"):
            if row.get(key):
                ctx["purpose"] = row[key]
        if row.get("会话标识"):
            ctx["session_id"] = row["会话标识"]
    return ctx


@router.post("/{module}/{entry_id}/claim")
async def wildcard_claim(module: str, entry_id: str, request: Request) -> dict[str, Any]:
    body = await _payload(request)
    ctx = _row_context(module, entry_id)
    # 路径 id 最可能是计划或许可/凭证行
    ctx.setdefault("plan_id", entry_id)
    ctx.update({k: v for k, v in body.items() if v not in (None, "")})
    return attribution_service.claim(ctx)


@router.post("/{module}/{entry_id}/approve")
async def wildcard_approve(module: str, entry_id: str, request: Request) -> dict[str, Any]:
    body = await _payload(request)
    ctx = _row_context(module, entry_id)
    if module in {"source_license", "license"}:
        ctx.setdefault("license_id", entry_id)
    else:
        ctx.setdefault("plan_id", entry_id)
    ctx.update({k: v for k, v in body.items() if v not in (None, "")})
    return attribution_service.approve_expansion(ctx)


@router.get("/{module}/{entry_id}/history")
async def wildcard_history(module: str, entry_id: str, request: Request) -> dict[str, Any]:
    if module == "session_manager":
        return attribution_service.session_history(entry_id, **dict(request.query_params))
    # 其它模块行：若能解析出计划，则返回该计划线索的领取历史
    ctx = _row_context(module, entry_id)
    plan_id = ctx.get("plan_id") or entry_id
    records = [r for r in __import__("app.store", fromlist=["store"]).store.rows("claim_record")
               if str(r.get("plan_id")) == str(plan_id) or str(r.get("lineage_key")) == str(plan_id)]
    history = [r.get("attribution") for r in records if r.get("attribution")]
    return {"ok": True, "found": bool(history), "history": history, "处理历史": history,
            "total": len(history)}


def __getattr__(name: str):
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(name)
    from app.services.attribution import resolve_dynamic_attr
    fn = resolve_dynamic_attr(name)
    if fn is not None:
        return fn
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

