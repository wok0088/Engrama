"""
API Key 认证中间件

从请求头 X-API-Key 提取 API Key，验证后将 tenant_id 和 project_id 注入请求 state。
渠道管理路由和文档路由跳过认证。
"""

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from cortex import config
from cortex.store.meta_store import MetaStore


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """API Key 认证中间件"""

    def __init__(self, app, meta_store: MetaStore):
        super().__init__(app)
        self._meta_store = meta_store

    async def dispatch(self, request: Request, call_next):
        """处理请求认证"""
        path = request.url.path

        # 检查是否是不需要认证的路径
        if path == "/":
            return await call_next(request)
        for prefix in config.AUTH_EXCLUDED_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        # 从 Header 提取 API Key
        api_key_value = request.headers.get("X-API-Key")
        if not api_key_value:
            return JSONResponse(
                status_code=401,
                content={"detail": "缺少 API Key，请在 X-API-Key 请求头中提供"},
            )

        # 验证 API Key
        api_key = self._meta_store.verify_api_key(api_key_value)
        if api_key is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "无效的 API Key"},
            )

        # 将认证信息注入请求 state
        request.state.tenant_id = api_key.tenant_id
        request.state.project_id = api_key.project_id
        request.state.api_key = api_key.key

        return await call_next(request)
