"""
API Key 认证中间件 + 管理员 Token 认证

- 记忆 API：从 X-API-Key 请求头提取 API Key 验证
- 渠道管理 API：从 X-Admin-Token 请求头验证管理员身份
- 文档和健康检查路由跳过认证

设计说明：
- MetaStore 使用 threading.local 进行线程级连接管理，这与 Starlette 的
  BaseHTTPMiddleware 在线程池中运行 sync 路由的模型兼容。每个线程拥有
  独立的 SQLite 连接，避免跨线程共享连接的并发问题。
- 路由函数定义为 sync（def）而非 async（async def），因此 FastAPI 会在
  线程池中运行它们，与 MetaStore 的 threading.local 策略保持一致。
"""

import asyncio
import hmac
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from engrama import config
from engrama.logger import get_logger
from engrama.store.base_meta_store import BaseMetaStore

logger = get_logger(__name__)


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """API Key + 管理员 Token 认证中间件"""

    def __init__(self, app):
        super().__init__(app)

    def _get_meta_store(self, request: Request):
        """延迟获取 meta_store 实例，避免与 lifespan 的重复初始化"""
        # middleware 在 init 时 app.state 可能还没准备好 meta_store
        # 因此在 request 时动态获取
        return getattr(request.app.state, "meta_store", None)

    async def dispatch(self, request: Request, call_next):
        """处理请求认证"""
        path = request.url.path

        # 公开路径：根据配置排除
        if any(path.startswith(prefix) for prefix in config.AUTH_EXCLUDED_PREFIXES) or path in ("/", "/health"):
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

        if not hmac.compare_digest(admin_token.encode(), config.ADMIN_TOKEN.encode()):
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

        meta_store = self._get_meta_store(request)
        if meta_store is None:
            logger.error("MetaStore 未初始化")
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "detail": "存储服务未就绪"},
            )

        api_key = await asyncio.to_thread(meta_store.verify_api_key, api_key_value)
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
