"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import attribution
from app.routers import resource
from app.routers import chains

# attribution 含 /api/session_manager/{id}/history 等扩展子路径，
# 必须先于通用 resource 注册，避免被动态资源路由的类型转换拦截。
ROUTERS = [attribution, resource, chains]
