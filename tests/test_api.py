"""
API 集成测试

使用 httpx 的 TestClient 测试 FastAPI 路由。
完整流程：注册租户 → 创建项目 → 生成 API Key → 使用 Key 操作记忆。
"""

import os

import pytest
from fastapi.testclient import TestClient

from engrama import config


@pytest.fixture(scope="module")
def client():
    """创建测试客户端"""
    from api.main import create_app
    app = create_app()

    with TestClient(app) as test_client:
        yield test_client


class TestAPI:
    """API 集成测试"""

    def _setup_channel(self, client) -> tuple[str, str, str, str]:
        """创建租户 + 项目 + API Key，返回 (tenant_id, project_id, api_key, key_id)"""
        headers = {"X-Admin-Token": config.ADMIN_TOKEN}
        
        # 注册租户
        resp = client.post("/v1/channels/tenants", json={"name": "测试公司"}, headers=headers)
        assert resp.status_code == 200
        tenant_id = resp.json()["id"]

        # 创建项目
        resp = client.post("/v1/channels/projects", json={
            "tenant_id": tenant_id, "name": "测试项目"
        }, headers=headers)
        assert resp.status_code == 200
        project_id = resp.json()["id"]

        # 生成 API Key
        resp = client.post("/v1/channels/api-keys", json={
            "tenant_id": tenant_id, "project_id": project_id
        }, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        api_key = data["key"]
        key_id = data["key_id"]

        return tenant_id, project_id, api_key, key_id

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
        headers = {"X-Admin-Token": config.ADMIN_TOKEN}
        resp = client.post("/v1/channels/tenants", json={"name": "携程旅行"}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "携程旅行"
        assert "id" in data

    def test_create_project(self, client):
        """创建项目"""
        headers = {"X-Admin-Token": config.ADMIN_TOKEN}
        resp = client.post("/v1/channels/tenants", json={"name": "租户"}, headers=headers)
        tenant_id = resp.json()["id"]

        resp = client.post("/v1/channels/projects", json={
            "tenant_id": tenant_id, "name": "酒店 AI"
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "酒店 AI"

    def test_generate_api_key(self, client):
        """生成 API Key（包含 key_id）"""
        _, _, api_key, key_id = self._setup_channel(client)
        assert api_key.startswith("eng_")
        assert key_id  # key_id 应非空

    def test_list_tenants(self, client):
        """列出租户"""
        headers = {"X-Admin-Token": config.ADMIN_TOKEN}
        client.post("/v1/channels/tenants", json={"name": "A"}, headers=headers)
        client.post("/v1/channels/tenants", json={"name": "B"}, headers=headers)
        resp = client.get("/v1/channels/tenants", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    # ----------------------------------------------------------
    # API Key 列出 / 吊销路由
    # ----------------------------------------------------------

    def test_list_api_keys(self, client):
        """列出项目下的 API Key"""
        tenant_id, project_id, _, key_id = self._setup_channel(client)
        headers = {"X-Admin-Token": config.ADMIN_TOKEN}

        resp = client.get("/v1/channels/api-keys", params={"project_id": project_id}, headers=headers)
        assert resp.status_code == 200
        keys = resp.json()
        assert len(keys) >= 1
        # 不应暴露完整 Key
        assert all("key" not in k or k.get("key") is None for k in keys)
        assert all("key_id" in k for k in keys)

    def test_revoke_api_key(self, client):
        """按 key_id 吊销 API Key"""
        tenant_id, project_id, api_key, key_id = self._setup_channel(client)
        headers = {"X-Admin-Token": config.ADMIN_TOKEN}

        # 吊销
        resp = client.delete(f"/v1/channels/api-keys/{key_id}", headers=headers)
        assert resp.status_code == 200

        # 再用原始 Key 调用应返回 401
        resp = client.get(
            "/v1/memories",
            params={"user_id": "u1"},
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 401

    # ----------------------------------------------------------
    # 删除租户路由
    # ----------------------------------------------------------

    def test_delete_tenant(self, client):
        """删除租户及其所有项目和 Key"""
        tenant_id, project_id, api_key, key_id = self._setup_channel(client)
        headers = {"X-Admin-Token": config.ADMIN_TOKEN}

        resp = client.delete(f"/v1/channels/tenants/{tenant_id}", headers=headers)
        assert resp.status_code == 200

        # 租户不存在了
        resp = client.get("/v1/channels/tenants", headers=headers)
        tenant_ids = [t["id"] for t in resp.json()]
        assert tenant_id not in tenant_ids

        # API Key 失效
        resp = client.get(
            "/v1/memories",
            params={"user_id": "u1"},
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 401

    def test_delete_tenant_nonexistent(self, client):
        """删除不存在的租户返回 404"""
        headers = {"X-Admin-Token": config.ADMIN_TOKEN}
        resp = client.delete("/v1/channels/tenants/nonexistent", headers=headers)
        assert resp.status_code == 404

    # ----------------------------------------------------------
    # delete_project 的 tenant 校验
    # ----------------------------------------------------------

    def test_delete_project_with_tenant_check(self, client):
        """删除项目时需传入正确的 tenant_id"""
        tenant_id, project_id, _, _ = self._setup_channel(client)
        headers = {"X-Admin-Token": config.ADMIN_TOKEN}

        # 用错误的 tenant_id 删除 → 404
        resp = client.delete(
            f"/v1/channels/projects/{project_id}",
            params={"tenant_id": "wrong_tenant"},
            headers=headers
        )
        assert resp.status_code == 404

        # 用正确的 tenant_id 删除 → 成功
        resp = client.delete(
            f"/v1/channels/projects/{project_id}",
            params={"tenant_id": tenant_id},
            headers=headers
        )
        assert resp.status_code == 200

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
        _, _, api_key, _ = self._setup_channel(client)
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

    def test_personal_key_behavior(self, client):
        """测试用户级 Key：可以省略 user_id，传入不同的 user_id 会 403"""
        tenant_id, project_id, project_key, _ = self._setup_channel(client)
        admin_headers = {"X-Admin-Token": config.ADMIN_TOKEN}

        # 1. 生成用户级 Key
        req = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "user_id": "zhangsan"
        }
        res = client.post("/v1/channels/api-keys", json=req, headers=admin_headers)
        personal_key = res.json()["key"]

        # 2. 正常调用：省略 user_id 自动使用绑定值
        resp1 = client.post(
            "/v1/memories",
            json={
                "content": "我喜欢打篮球",
                "memory_type": "preference",
            },
            headers={"X-API-Key": personal_key},
        )
        assert resp1.status_code == 200
        assert resp1.json()["user_id"] == "zhangsan"

        # 3. 越权调用：传入不同的 user_id 返回 403
        resp2 = client.post(
            "/v1/memories",
            json={
                "user_id": "lisi",
                "content": "我是 Lisi",
                "memory_type": "factual",
            },
            headers={"X-API-Key": personal_key},
        )
        assert resp2.status_code == 403
        assert "已绑定用户" in resp2.json()["detail"]

        # 4. GET 路由：省略 user_id 进行列出
        fragment_id = resp1.json()["id"]
        resp_list = client.get(
            "/v1/memories",
            headers={"X-API-Key": personal_key},
        )
        assert resp_list.status_code == 200
        assert len(resp_list.json()) == 1
        assert resp_list.json()[0]["user_id"] == "zhangsan"

        # 5. PUT 路由：省略 user_id 进行更新
        resp_put = client.put(
            f"/v1/memories/{fragment_id}",
            json={
                "content": "我喜欢踢足球",
            },
            headers={"X-API-Key": personal_key},
        )
        assert resp_put.status_code == 200
        assert resp_put.json()["content"] == "我喜欢踢足球"

        # 6. /users/me/stats 路由：省略 user_id 获取统计 (此时有一条 preference 记忆)
        resp_stats = client.get(
            "/v1/users/me/stats",
            headers={"X-API-Key": personal_key},
        )
        assert resp_stats.status_code == 200
        stats_data = resp_stats.json()
        assert stats_data["user_id"] == "zhangsan"
        assert stats_data["total_memories"] == 1
        assert stats_data["by_type"].get("preference") == 1

        # 7. 项目级 Key 调用 /users/me/stats 应该返回 400
        resp_proj_stats = client.get(
            "/v1/users/me/stats",
            headers={"X-API-Key": project_key},
        )
        assert resp_proj_stats.status_code == 400
        assert "user_id" in resp_proj_stats.text

        # 8. DELETE 路由：省略 user_id 进行删除
        resp_del = client.delete(
            f"/v1/memories/{fragment_id}",
            headers={"X-API-Key": personal_key},
        )
        assert resp_del.status_code == 200

    def test_update_memory(self, client):
        """测试独立记忆更新（部分更新、更新不存在片段等）"""
        _, _, project_key, _ = self._setup_channel(client)
        headers = {"X-API-Key": project_key}

        # 1. 准备测试数据
        create_resp = client.post(
            "/v1/memories",
            json={"user_id": "u1", "content": "原始数据", "memory_type": "factual", "tags": ["tag1", "tag2"]},
            headers=headers
        )
        assert create_resp.status_code == 200
        frag_id = create_resp.json()["id"]

        # 2. 项目级 Key 部分更新（只更新 tags，不更新 content）
        update_resp1 = client.put(
            f"/v1/memories/{frag_id}",
            json={"user_id": "u1", "tags": ["tag_new"]},
            headers=headers
        )
        assert update_resp1.status_code == 200
        data1 = update_resp1.json()
        assert data1["content"] == "原始数据"
        assert data1["tags"] == ["tag_new"]

        # 3. 更新不存在的记忆 (404)
        update_resp2 = client.put(
            "/v1/memories/invalid_id",
            json={"user_id": "u1", "content": "新内容"},
            headers=headers
        )
        assert update_resp2.status_code == 404

    def test_search_memories(self, client):
        """语义搜索"""
        _, _, api_key, _ = self._setup_channel(client)
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
        if resp.status_code != 200:
            print("test_search_memories 400 error output:", resp.json())
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] > 0
        assert "score" in data["results"][0]

    def test_list_memories(self, client):
        """列出记忆"""
        _, _, api_key, _ = self._setup_channel(client)
        headers = {"X-API-Key": api_key}

        client.post("/v1/memories", json={
            "user_id": "u1", "content": "记忆内容", "memory_type": "factual",
        }, headers=headers)

        resp = client.get("/v1/memories", params={"user_id": "u1"}, headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_delete_memory(self, client):
        """删除记忆"""
        _, _, api_key, _ = self._setup_channel(client)
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
        _, _, api_key, _ = self._setup_channel(client)
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
        assert data["count"] == 2
        assert data["messages"][0]["role"] == "user"

    # ----------------------------------------------------------
    # 统计信息
    # ----------------------------------------------------------

    def test_user_stats(self, client):
        """获取统计信息"""
        _, _, api_key, _ = self._setup_channel(client)
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
