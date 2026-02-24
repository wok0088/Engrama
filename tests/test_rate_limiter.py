"""
验证速率限制中间件的测试 (RateLimiterMiddleware)
"""

import os
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from engrama import config


@pytest.fixture
def client_with_rate_limit(tmp_dir, monkeypatch):
    """使用限制频率很低（10次/分）的配置启动客户端，并 Mock Redis"""
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MINUTE", 13)
    monkeypatch.setattr(config, "REDIS_URL", "redis://localhost")
    monkeypatch.setattr(config, "ADMIN_TOKEN", "")
    monkeypatch.setattr(config, "DATA_DIR", tmp_dir)
    monkeypatch.setattr(config, "CHROMA_PERSIST_DIR", os.path.join(tmp_dir, "chroma_db"))
    monkeypatch.setattr(config, "SQLITE_DB_PATH", os.path.join(tmp_dir, "engrama_meta.db"))

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


def test_rate_limiter_exceeds_limit(client_with_rate_limit):
    """测试超过频率限制会被拒绝，并测试状态 429"""

    # 获取一个正常的 api key 用于测试
    resp = client_with_rate_limit.post("/v1/channels/tenants", json={"name": "t1"})
    tenant_id = resp.json()["id"]

    resp = client_with_rate_limit.post("/v1/channels/projects", json={"tenant_id": tenant_id, "name": "p1"})
    project_id = resp.json()["id"]

    resp = client_with_rate_limit.post("/v1/channels/api-keys", json={"tenant_id": tenant_id, "project_id": project_id})
    api_key = resp.json()["key"]

    # 模拟发送 12 个请求 (限制为 10)
    status_codes = []

    for _ in range(12):
        resp = client_with_rate_limit.post(
            "/v1/memories",
            json={"user_id": "u1", "content": "测试流量", "memory_type": "factual"},
            headers={"X-API-Key": api_key}
        )
        status_codes.append(resp.status_code)

    # 前 10 次应该成功，最后 2 次应该是 429
    assert status_codes.count(200) == 10
    assert status_codes[-2:] == [429, 429]
