"""
API Key 认证中间件 + 管理员 Token 认证

- 记忆 API：从 X-API-Key 请求头提取 API Key 验证
- 渠道管理 API：从 X-Admin-Token 请求头验证管理员身份
- 文档和健康检查路由跳过认证
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from cortex import config
from cortex.logger import get_logger
from cortex.store.meta_store import MetaStore

logger = get_logger(__name__)


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """API Key + 管理员 Token 认证中间件"""

    def __init__(self, app, meta_store: MetaStore):
        super().__init__(app)
        self._meta_store = meta_store

    async def dispatch(self, request: Request, call_next):
        """处理请求认证"""
        path = request.url.path

        # 公开路径：根、健康检查、文档
        if path in ("/", "/health") or path.startswith(("/docs", "/redoc", "/openapi.json")):
            return await call_next(request)

        # 渠道管理路径：需要管理员 Token
        if path.startswith("/v1/channels"):
            return await self._check_admin_token(request, call_next)

        # 业务 API：需要 API Key
        return await self._check_api_key(request, call_next)

    async def _check_admin_token(self, request: Request, call_next):
        """验证管理员 Token"""
        # 如果未设置管理员 Token（开发模式），允许免认证访问
        if not config.ADMIN_TOKEN:
            return await call_next(request)

        admin_token = request.headers.get("X-Admin-Token")
        if not admin_token:
            logger.warning("渠道管理请求缺少管理员 Token: %s", request.url.path)
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "detail": "缺少管理员 Token，请在 X-Admin-Token 请求头中提供"},
            )

        if admin_token != config.ADMIN_TOKEN:
            logger.warning("无效的管理员 Token 尝试: %s", request.url.path)
            return JSONResponse(
                status_code=403,
                content={"error": "forbidden", "detail": "无效的管理员 Token"},
            )

        return await call_next(request)

    async def _check_api_key(self, request: Request, call_next):
        """验证 API Key"""
        api_key_value = request.headers.get("X-API-Key")
        if not api_key_value:
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "detail": "缺少 API Key，请在 X-API-Key 请求头中提供"},
            )

        api_key = self._meta_store.verify_api_key(api_key_value)
        if api_key is None:
            logger.warning("无效的 API Key 尝试")
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "detail": "无效的 API Key"},
            )

        # 将认证信息注入请求 state
        request.state.tenant_id = api_key.tenant_id
        request.state.project_id = api_key.project_id
        request.state.api_key = api_key.key
        request.state.bound_user_id = api_key.user_id  # None 为项目级 Key

        return await call_next(request)
