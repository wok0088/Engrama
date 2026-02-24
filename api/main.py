"""
Engrama REST API 入口

FastAPI 应用初始化，注册路由、中间件、CORS 和全局异常处理。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from engrama import config
from engrama.logger import get_logger
from engrama.store.qdrant_store import QdrantStore
from engrama.store import create_meta_store
from engrama.memory_manager import MemoryManager
from engrama.channel_manager import ChannelManager
from api.middleware import ApiKeyAuthMiddleware
from api.rate_limiter import RateLimiterMiddleware
from api.routes import memories, channels

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化存储和管理器"""
    logger.info("Engrama %s 正在启动...", config.API_VERSION)
    logger.info("Storage DB: %s", config.DB_TYPE)
    logger.info("Embedding API: %s", config.EMBEDDING_API_URL)
    logger.info("数据目录: %s", config.DATA_DIR)

    # 初始化存储层
    meta_store = create_meta_store()
    vector_store = QdrantStore(meta_store=meta_store)

    # 初始化业务层
    app.state.memory_manager = MemoryManager(
        vector_store=vector_store, meta_store=meta_store
    )
    app.state.channel_manager = ChannelManager(
        meta_store=meta_store, vector_store=vector_store
    )
    app.state.meta_store = meta_store

    logger.info("Engrama 启动完成 ✅")
    yield
    logger.info("Engrama 正在关闭...")


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用"""
    app = FastAPI(
        title=config.API_TITLE,
        version=config.API_VERSION,
        description=config.API_DESCRIPTION,
        lifespan=lifespan,
    )

    # 注册路由
    app.include_router(memories.router)
    app.include_router(channels.router)

    # CORS 配置
    origins = config.CORS_ORIGINS
    allow_credentials = True
    if origins == "*":
        allow_origins = ["*"]
        allow_credentials = False
    else:
        allow_origins = [o.strip() for o in origins.split(",") if o.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 速率限制中间件
    if config.RATE_LIMIT_PER_MINUTE > 0:
        app.add_middleware(
            RateLimiterMiddleware,
            max_requests_per_minute=config.RATE_LIMIT_PER_MINUTE,
        )

    # API Key 认证中间件
    app.add_middleware(ApiKeyAuthMiddleware)

    # ----------------------------------------------------------
    # 全局异常处理
    # ----------------------------------------------------------

    @app.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError):
        """Pydantic 验证错误 → 400"""
        return JSONResponse(
            status_code=400,
            content={"error": "validation_error", "detail": exc.errors()},
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        """业务逻辑错误 → 400"""
        return JSONResponse(
            status_code=400,
            content={"error": "bad_request", "detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def general_error_handler(request: Request, exc: Exception):
        """未预期的异常 → 500"""
        logger.error("未预期的异常: %s %s → %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": "服务器内部错误，请稍后重试"},
        )

    # ----------------------------------------------------------
    # 基础端点
    # ----------------------------------------------------------

    @app.get("/", tags=["根"])
    async def root():
        """Engrama API 欢迎页"""
        return {
            "name": config.API_TITLE,
            "version": config.API_VERSION,
            "docs": "/docs",
        }

    @app.get("/health", tags=["健康检查"])
    async def health():
        """健康检查端点"""
        return {"status": "ok"}

    return app


# 应用实例
app = create_app()
