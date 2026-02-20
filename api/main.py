"""
Cortex REST API 入口

FastAPI 应用初始化，注册路由和中间件。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from cortex import config
from cortex.store.vector_store import VectorStore
from cortex.store.meta_store import MetaStore
from cortex.memory_manager import MemoryManager
from cortex.channel_manager import ChannelManager
from api.middleware import ApiKeyAuthMiddleware
from api.routes import memories, channels


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化存储和管理器"""
    # 初始化存储层
    vector_store = VectorStore()
    meta_store = MetaStore()

    # 初始化业务层
    app.state.memory_manager = MemoryManager(
        vector_store=vector_store, meta_store=meta_store
    )
    app.state.channel_manager = ChannelManager(meta_store=meta_store)

    # 将 meta_store 存储到 app state，供中间件使用
    app.state.meta_store = meta_store

    yield


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

    # 注册认证中间件
    # 注意：中间件在 lifespan 之后才会被调用，此时 meta_store 已初始化
    # 但 Starlette 的中间件设计要求在 app 创建时注册
    # 因此使用延迟初始化的方式
    meta_store = MetaStore()
    app.add_middleware(ApiKeyAuthMiddleware, meta_store=meta_store)

    # 基础端点
    @app.get("/", tags=["根"])
    async def root():
        """Cortex API 欢迎页"""
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

