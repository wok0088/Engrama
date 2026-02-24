"""
速率限制中间件

优先使用 Redis 分布式滑动窗口（ENGRAMA_REDIS_URL + ENGRAMA_RATE_LIMIT）。
如果 Redis 不可用或未配置，自动降级为内存滑动窗口限流。
"""

import time
import asyncio
import threading
from collections import defaultdict
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from engrama import config
from engrama.logger import get_logger

logger = get_logger(__name__)


class _InMemoryRateLimiter:
    """基于内存的滑动窗口限流（单实例，线程安全）"""

    def __init__(self, max_rpm: int):
        self._max_rpm = max_rpm
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_rate_limited(self, client_id: str) -> bool:
        """检查是否超速，返回 True 表示应拒绝"""
        now = time.time()
        window_start = now - 60.0

        with self._lock:
            timestamps = self._windows[client_id]
            # 清理过期记录
            self._windows[client_id] = [
                t for t in timestamps if t > window_start
            ]
            # 判断是否超限
            if len(self._windows[client_id]) >= self._max_rpm:
                return True
            # 记录本次请求
            self._windows[client_id].append(now)
            return False


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """速率限制中间件（Redis 优先，内存降级）"""

    def __init__(self, app, max_requests_per_minute: int = 0):
        super().__init__(app)
        self._max_rpm = max_requests_per_minute
        self._redis = None
        self._memory_limiter: Optional[_InMemoryRateLimiter] = None

        if self._max_rpm <= 0:
            return

        # 尝试连接 Redis
        if config.REDIS_URL:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(config.REDIS_URL, decode_responses=True)
                logger.info("Redis 速率限制器初始化完成: %s", config.REDIS_URL)
            except Exception as e:
                logger.warning("Redis 连接初始化失败，将降级为内存限流: %s", e)

        # 内存降级（即使 Redis 配置了也会创建，用于 Redis 运行时异常时降级）
        self._memory_limiter = _InMemoryRateLimiter(self._max_rpm)
        if not self._redis:
            logger.info("使用内存速率限制器（max_rpm=%d）", self._max_rpm)

    async def dispatch(self, request: Request, call_next):
        """检查速率限制"""
        if self._max_rpm <= 0:
            return await call_next(request)

        # 使用 API Key 或 IP 作为限制标识
        client_id = (
            request.headers.get("X-API-Key")
            or (request.client.host if request.client else "unknown")
        )

        # 优先使用 Redis
        if self._redis is not None:
            result = await self._check_redis(client_id)
            if result is not None:
                return result if isinstance(result, JSONResponse) else await call_next(request)

        # Redis 不可用或失败，降级为内存限流
        if self._memory_limiter is not None:
            if self._memory_limiter.is_rate_limited(client_id):
                logger.warning("速率限制触发(内存): client=%s", client_id[:16])
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limited",
                        "detail": f"请求过于频繁，每分钟最多 {self._max_rpm} 次请求",
                    },
                )

        return await call_next(request)

    async def _check_redis(self, client_id: str):
        """
        Redis 限流检查。
        返回 JSONResponse 表示拒绝，True 表示放行，None 表示 Redis 异常需降级。
        """
        now = time.time()
        window_start = now - 60.0
        redis_key = f"rate_limit:{client_id}"

        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(redis_key, "-inf", window_start)
                pipe.zadd(redis_key, {str(now): now})
                pipe.zcard(redis_key)
                pipe.expire(redis_key, 60)
                results = await pipe.execute()

            request_count = results[2]

            if request_count > self._max_rpm:
                logger.warning("速率限制触发(Redis): client=%s, requests=%d", client_id[:16], request_count)
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limited",
                        "detail": f"请求过于频繁，每分钟最多 {self._max_rpm} 次请求",
                    },
                )
            return True  # 放行

        except Exception as e:
            logger.error("Redis 速率限制异常，降级为内存限流: %s", e)
            return None  # 降级信号
