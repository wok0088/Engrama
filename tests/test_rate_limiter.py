"""
验证速率限制中间件的测试 (RateLimiterMiddleware)
"""

import os
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from engrama import config


# ----------------------------------------------------------
# Redis 限流测试（Mock Redis）
# ----------------------------------------------------------

@pytest.fixture
def client_with_redis_rate_limit(tmp_dir, monkeypatch):
    """使用限制频率（13次/分）的配置启动客户端，并 Mock Redis"""
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MINUTE", 13)
    monkeypatch.setattr(config, "REDIS_URL", "redis://localhost")
    admin_token = config.ADMIN_TOKEN or "fallback-secret-for-test"
    monkeypatch.setattr(config, "ADMIN_TOKEN", admin_token)
    monkeypatch.setattr(config, "DATA_DIR", tmp_dir)



    class DummyPipeline:
        def __init__(self):
            self._call_count = 0

        def zremrangebyscore(self, *args, **kwargs): pass
        def zadd(self, *args, **kwargs): pass
        def zcard(self, *args, **kwargs): pass
        def expire(self, *args, **kwargs): pass

        async def execute(self):
            self._call_count += 1
            return [0, 1, self._call_count, 1]

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class DummyRedis:
        def pipeline(self, transaction=True):
            if not hasattr(self, '_pipe'):
                self._pipe = DummyPipeline()
            return self._pipe

    from unittest.mock import patch
    with patch('redis.asyncio.from_url', return_value=DummyRedis()):
        from api.main import create_app
        app = create_app()
        with TestClient(app) as client:
            yield client


def test_rate_limiter_exceeds_limit(client_with_redis_rate_limit):
    """测试超过频率限制会被拒绝（Redis 模式），并测试状态 429"""
    # 获取一个正常的 api key 用于测试
    admin_headers = {"X-Admin-Token": config.ADMIN_TOKEN}
    resp = client_with_redis_rate_limit.post("/v1/channels/tenants", json={"name": "t1"}, headers=admin_headers)
    tenant_id = resp.json()["id"]

    resp = client_with_redis_rate_limit.post("/v1/channels/projects", json={"tenant_id": tenant_id, "name": "p1"}, headers=admin_headers)
    project_id = resp.json()["id"]

    resp = client_with_redis_rate_limit.post("/v1/channels/api-keys", json={"tenant_id": tenant_id, "project_id": project_id}, headers=admin_headers)
    api_key = resp.json()["key"]

    # 模拟发送 15 个请求 (限制为 13)
    status_codes = []
    for _ in range(15):
        resp = client_with_redis_rate_limit.post(
            "/v1/memories",
            json={"user_id": "u1", "content": "测试流量", "memory_type": "factual"},
            headers={"X-API-Key": api_key}
        )
        status_codes.append(resp.status_code)

    # 前 13 次应该成功（前 3 次是渠道管理 + 13 次记忆请求中的前 10 次放行）
    assert 429 in status_codes, "应有请求被限流"
    assert 200 in status_codes, "应有请求被放行"


# ----------------------------------------------------------
# 内存降级测试（无 Redis）
# ----------------------------------------------------------

@pytest.fixture
def client_with_memory_rate_limit(tmp_dir, monkeypatch):
    """使用内存限流模式（无 Redis）"""
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MINUTE", 5)
    monkeypatch.setattr(config, "REDIS_URL", "")  # 无 Redis
    admin_token = config.ADMIN_TOKEN or "fallback-secret-for-test"
    monkeypatch.setattr(config, "ADMIN_TOKEN", admin_token)
    monkeypatch.setattr(config, "DATA_DIR", tmp_dir)



    from api.main import create_app
    app = create_app()
    with TestClient(app) as client:
        yield client


def test_memory_rate_limiter_works(client_with_memory_rate_limit):
    """测试内存降级模式下限流仍生效"""
    # 获取 api key
    admin_headers = {"X-Admin-Token": config.ADMIN_TOKEN}
    resp = client_with_memory_rate_limit.post("/v1/channels/tenants", json={"name": "t1"}, headers=admin_headers)
    tenant_id = resp.json()["id"]

    resp = client_with_memory_rate_limit.post("/v1/channels/projects", json={"tenant_id": tenant_id, "name": "p1"}, headers=admin_headers)
    project_id = resp.json()["id"]

    resp = client_with_memory_rate_limit.post("/v1/channels/api-keys", json={"tenant_id": tenant_id, "project_id": project_id}, headers=admin_headers)
    api_key = resp.json()["key"]

    # 发送 8 个请求（限制为 5）
    status_codes = []
    for _ in range(8):
        resp = client_with_memory_rate_limit.post(
            "/v1/memories",
            json={"user_id": "u1", "content": "测试流量", "memory_type": "factual"},
            headers={"X-API-Key": api_key}
        )
        status_codes.append(resp.status_code)

    # 应有请求被 429 拒绝
    assert 429 in status_codes, "内存限流应该触发 429"
    assert 200 in status_codes, "应有请求被放行"


# ----------------------------------------------------------
# 不超限放行测试
# ----------------------------------------------------------

def test_rate_limiter_allows_under_limit(client_with_memory_rate_limit):
    """测试未超限的请求正常放行"""
    admin_headers = {"X-Admin-Token": config.ADMIN_TOKEN}
    resp = client_with_memory_rate_limit.post("/v1/channels/tenants", json={"name": "t1"}, headers=admin_headers)
    tenant_id = resp.json()["id"]

    resp = client_with_memory_rate_limit.post("/v1/channels/projects", json={"tenant_id": tenant_id, "name": "p1"}, headers=admin_headers)
    project_id = resp.json()["id"]

    resp = client_with_memory_rate_limit.post("/v1/channels/api-keys", json={"tenant_id": tenant_id, "project_id": project_id}, headers=admin_headers)
    api_key = resp.json()["key"]

    # 只发 1 个请求，远未超限
    resp = client_with_memory_rate_limit.post(
        "/v1/memories",
        json={"user_id": "u1", "content": "安全请求", "memory_type": "factual"},
        headers={"X-API-Key": api_key}
    )
    assert resp.status_code == 200
