"""领取/核准记录与采集会话归属的只读查询服务。"""
from __future__ import annotations

from app.services.base import BaseModuleService
from app.store import store


class ClaimRecordService(BaseModuleService):
    MODULE = "claim_record"
    ENTITY = "领取核准记录"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["领取标识", "核准记录标识", "计划标识", "实际采用计划", "来源站点",
                   "用途", "许可标识", "许可版本", "会话标识", "处理结论"]
    REQUIRED_FIELDS: list[str] = []
    STATUS_ORDER = ["已核准", "待审核"]
    ACTION_RULES: dict[str, str] = {}
    NEGATIVE_ACTIONS: list[str] = []

    def domain_replay(self, claim_key: str) -> dict:
        from app.services.attribution import attribution_service
        rows = store.rows("claim_record")
        record = next((r for r in rows if str(r.get("claim_key")) == str(claim_key)), None)
        if record is None:
            return {"ok": False, "found": False, "message": "原核准记录不存在"}
        return attribution_service._replay(record)


class SessionAttributionService(ClaimRecordService):
    """语义别名：采集会话归属数据。"""

    ENTITY = "采集会话归属"
