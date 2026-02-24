"""
分布式速率限制器

基于 Redis 的滑动窗口速率限制，通过 ENGRAMA_RATE_LIMIT 和 ENGRAMA_REDIS_URL 配置。
如果 Redis 连接失败，自动降级为直接放行（Fail-Open）。
"""

import time
import asyncio
from typing import Optional
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import redis.asyncio as redis
from redis.asyncio import Redis

from engrama import config
from engrama.logger import get_logger

logger = get_logger(__name__)


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """基于 Redis 的分布式滑动窗口速率限制中间件"""

    def __init__(self, app, max_requests_per_minute: int = 0):
        super().__init__(app)
        self._max_rpm = max_requests_per_minute
        self._redis: Optional[Redis] = None

        if config.REDIS_URL and self._max_rpm > 0:
            try:
                self._redis = redis.from_url(config.REDIS_URL, decode_responses=True)
                logger.info("Redis 速率限制器初始化完成: %s", config.REDIS_URL)
            except Exception as e:
                logger.error("Redis 连接初始化失败，速率限制将失效: %s", e)

    async def dispatch(self, request: Request, call_next):
        """检查速率限制"""
        if self._max_rpm <= 0 or self._redis is None:
            return await call_next(request)

        # 使用 API Key 或 IP 作为限制标识
        client_id = (
            request.headers.get("X-API-Key")
            or (request.client.host if request.client else "unknown")
        )

        now = time.time()
        window_start = now - 60.0
        redis_key = f"rate_limit:{client_id}"

        try:
            # 使用 Pipeline 执行 ZREMRANGEBYSCORE, ZADD, ZCARD
            async with self._redis.pipeline(transaction=True) as pipe:
                # 移除 60 秒前的请求
                pipe.zremrangebyscore(redis_key, "-inf", window_start)
                # 记录当前请求 (score和value都使用时间戳)
                pipe.zadd(redis_key, {str(now): now})
                # 获取当前窗口内的请求数
                pipe.zcard(redis_key)
                # 设置过期时间（60秒后如果没新请求自动清理key）
                pipe.expire(redis_key, 60)

                results = await pipe.execute()

            request_count = results[2]  # zcard 的结果

            if request_count > self._max_rpm:
                logger.warning("速率限制触发: client=%s, requests=%d", client_id[:16], request_count)
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limited",
                        "detail": f"请求过于频繁，每分钟最多 {self._max_rpm} 次请求",
                    },
                )

        except Exception as e:
            # 降级：如果 Redis 挂了，直接放行，记录错误
            logger.error("Redis 速率限制异常，请求已放行: %s", e)

        return await call_next(request)
