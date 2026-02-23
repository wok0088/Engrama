"""
API 集成测试

使用 httpx 的 TestClient 测试 FastAPI 路由。
完整流程：注册租户 → 创建项目 → 生成 API Key → 使用 Key 操作记忆。
"""

import os
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient

from cortex.store.vector_store import VectorStore
from cortex.store.meta_store import MetaStore
from cortex.memory_manager import MemoryManager
from cortex.channel_manager import ChannelManager


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def client(tmp_dir):
    """创建测试客户端，使用临时目录存储数据"""
    # 需要在 import 之前设置环境变量
    os.environ["CORTEX_DATA_DIR"] = tmp_dir

    # 重新导入以使用新配置
    from api.main import create_app
    from cortex.store.vector_store import VectorStore
    from cortex.store.meta_store import MetaStore

    app = create_app()

    # 手动初始化 app state（因为 lifespan 在 TestClient 中也会运行）
    # 但我们需要覆盖中间件的 meta_store 以使用临时目录
    with TestClient(app) as client:
        yield client

    # 清理环境变量
    del os.environ["CORTEX_DATA_DIR"]


class TestAPI:
    """API 集成测试"""

    def _setup_channel(self, client) -> tuple[str, str, str]:
        """创建租户 + 项目 + API Key，返回 (tenant_id, project_id, api_key)"""
        # 注册租户
        resp = client.post("/v1/channels/tenants", json={"name": "测试公司"})
        assert resp.status_code == 200
        tenant_id = resp.json()["id"]

        # 创建项目
        resp = client.post("/v1/channels/projects", json={
            "tenant_id": tenant_id, "name": "测试项目"
        })
        assert resp.status_code == 200
        project_id = resp.json()["id"]

        # 生成 API Key
        resp = client.post("/v1/channels/api-keys", json={
            "tenant_id": tenant_id, "project_id": project_id
        })
        assert resp.status_code == 200
        api_key = resp.json()["key"]

        return tenant_id, project_id, api_key

    # ----------------------------------------------------------
    # 基础端点
    # ----------------------------------------------------------

    def test_root(self, client):
        """根路径返回项目信息"""
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "Engrama" in data["name"]

    def test_health(self, client):
        """健康检查"""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    # ----------------------------------------------------------
    # 渠道管理（无需认证）
    # ----------------------------------------------------------

    def test_register_tenant(self, client):
        """注册租户"""
        resp = client.post("/v1/channels/tenants", json={"name": "携程旅行"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "携程旅行"
        assert "id" in data

    def test_create_project(self, client):
        """创建项目"""
        resp = client.post("/v1/channels/tenants", json={"name": "租户"})
        tenant_id = resp.json()["id"]

        resp = client.post("/v1/channels/projects", json={
            "tenant_id": tenant_id, "name": "酒店 AI"
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "酒店 AI"

    def test_generate_api_key(self, client):
        """生成 API Key"""
        _, _, api_key = self._setup_channel(client)
        assert api_key.startswith("ctx_")

    def test_list_tenants(self, client):
        """列出租户"""
        client.post("/v1/channels/tenants", json={"name": "A"})
        client.post("/v1/channels/tenants", json={"name": "B"})
        resp = client.get("/v1/channels/tenants")
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    # ----------------------------------------------------------
    # 认证测试
    # ----------------------------------------------------------

    def test_auth_required(self, client):
        """记忆 API 需要 API Key"""
        resp = client.get("/v1/memories", params={"user_id": "u1"})
        assert resp.status_code == 401

    def test_auth_invalid_key(self, client):
        """无效的 API Key 被拒绝"""
        resp = client.get(
            "/v1/memories",
            params={"user_id": "u1"},
            headers={"X-API-Key": "invalid_key"},
        )
        assert resp.status_code == 401

    # ----------------------------------------------------------
    # 记忆 CRUD（需要认证）
    # ----------------------------------------------------------

    def test_add_memory(self, client):
        """添加记忆"""
        _, _, api_key = self._setup_channel(client)
        resp = client.post(
            "/v1/memories",
            json={
                "user_id": "u1",
                "content": "喜欢安静的环境",
                "memory_type": "preference",
            },
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "喜欢安静的环境"
        assert data["memory_type"] == "preference"

    def test_search_memories(self, client):
        """语义搜索"""
        _, _, api_key = self._setup_channel(client)
        headers = {"X-API-Key": api_key}

        # 添加几条记忆
        for content, mt in [
            ("生日是 1990-03-15", "factual"),
            ("喜欢安静的环境", "preference"),
            ("2025 年 1 月咨询了八字", "episodic"),
        ]:
            client.post("/v1/memories", json={
                "user_id": "u1", "content": content, "memory_type": mt,
            }, headers=headers)

        # 搜索
        resp = client.post("/v1/memories/search", json={
            "user_id": "u1", "query": "生日",
        }, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0
        assert "score" in data["results"][0]

    def test_list_memories(self, client):
        """列出记忆"""
        _, _, api_key = self._setup_channel(client)
        headers = {"X-API-Key": api_key}

        client.post("/v1/memories", json={
            "user_id": "u1", "content": "记忆内容", "memory_type": "factual",
        }, headers=headers)

        resp = client.get("/v1/memories", params={"user_id": "u1"}, headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_delete_memory(self, client):
        """删除记忆"""
        _, _, api_key = self._setup_channel(client)
        headers = {"X-API-Key": api_key}

        # 添加
        resp = client.post("/v1/memories", json={
            "user_id": "u1", "content": "待删除", "memory_type": "factual",
        }, headers=headers)
        fragment_id = resp.json()["id"]

        # 删除
        resp = client.delete(
            f"/v1/memories/{fragment_id}",
            params={"user_id": "u1"},
            headers=headers,
        )
        assert resp.status_code == 200

        # 验证已删除
        resp = client.get("/v1/memories", params={"user_id": "u1"}, headers=headers)
        assert len(resp.json()) == 0

    # ----------------------------------------------------------
    # 会话历史
    # ----------------------------------------------------------

    def test_session_history(self, client):
        """获取会话历史"""
        _, _, api_key = self._setup_channel(client)
        headers = {"X-API-Key": api_key}

        import time
        # 添加会话消息
        for content, role in [
            ("你好", "user"),
            ("你好！有什么可以帮你？", "assistant"),
        ]:
            time.sleep(0.01)
            client.post("/v1/memories", json={
                "user_id": "u1", "content": content,
                "memory_type": "session",
                "role": role, "session_id": "s1",
            }, headers=headers)

        # 获取历史
        resp = client.get(
            "/v1/sessions/s1/history",
            params={"user_id": "u1"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "s1"
        assert data["total"] == 2
        assert data["messages"][0]["role"] == "user"

    # ----------------------------------------------------------
    # 统计信息
    # ----------------------------------------------------------

    def test_user_stats(self, client):
        """获取统计信息"""
        _, _, api_key = self._setup_channel(client)
        headers = {"X-API-Key": api_key}

        client.post("/v1/memories", json={
            "user_id": "u1", "content": "事实", "memory_type": "factual",
        }, headers=headers)
        client.post("/v1/memories", json={
            "user_id": "u1", "content": "偏好", "memory_type": "preference",
        }, headers=headers)

        resp = client.get("/v1/users/u1/stats", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_memories"] == 2
        assert data["by_type"]["factual"] == 1
