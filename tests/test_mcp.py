"""
MCP Server 测试

测试 MCP 鉴权机制和 Tool 调用（通过直接调用函数验证）。
覆盖项目级 Key（B 端）和用户级 Key（C 端）两种场景。
"""

import json
import os

import pytest

from engrama.store.base_meta_store import BaseMetaStore
from engrama.store import create_meta_store
from engrama.store.qdrant_store import QdrantStore
from engrama.memory_manager import MemoryManager


@pytest.fixture
def services():
    """初始化业务层服务和一个项目级 API Key"""
    meta_store = create_meta_store()

    vector_store = QdrantStore(meta_store=meta_store)
    memory_manager = MemoryManager(vector_store=vector_store, meta_store=meta_store)

    # 创建租户 + 项目
    tenant = meta_store.create_tenant("测试租户")
    project = meta_store.create_project(tenant_id=tenant.id, name="测试项目")

    # 项目级 Key（B 端）
    service_key = meta_store.generate_api_key(tenant_id=tenant.id, project_id=project.id)
    # 用户级 Key（C 端）
    personal_key = meta_store.generate_api_key(tenant_id=tenant.id, project_id=project.id, user_id="zhangsan")

    yield {
        "vector_store": vector_store,
        "meta_store": meta_store,
        "memory_manager": memory_manager,
        "tenant_id": tenant.id,
        "project_id": project.id,
        "service_key": service_key.key,
        "personal_key": personal_key.key,
    }


class TestMCPAuth:
    """MCP 鉴权测试"""

    def test_verify_service_key(self, services):
        """项目级 Key 验证成功，user_id 为 None"""
        from mcp_server.server import verify_and_bind

        ctx = verify_and_bind(services["service_key"], services["meta_store"])
        assert ctx.tenant_id == services["tenant_id"]
        assert ctx.project_id == services["project_id"]
        assert ctx.user_id is None  # 项目级 Key 无绑定用户

    def test_verify_personal_key(self, services):
        """用户级 Key 验证成功，user_id 自动绑定"""
        from mcp_server.server import verify_and_bind

        ctx = verify_and_bind(services["personal_key"], services["meta_store"])
        assert ctx.tenant_id == services["tenant_id"]
        assert ctx.project_id == services["project_id"]
        assert ctx.user_id == "zhangsan"  # 用户级 Key 绑定用户

    def test_verify_empty_key(self, services):
        """空 API Key 导致退出"""
        from mcp_server.server import verify_and_bind

        with pytest.raises(SystemExit):
            verify_and_bind("", services["meta_store"])

    def test_verify_invalid_key(self, services):
        """无效 API Key 导致退出"""
        from mcp_server.server import verify_and_bind

        with pytest.raises(SystemExit):
            verify_and_bind("eng_invalid_key_12345", services["meta_store"])


class TestMCPToolsServiceKey:
    """MCP Tool 功能测试（项目级 Key，B 端场景）"""

    def _bind_context(self, services):
        """绑定项目级 Key 的鉴权上下文"""
        import mcp_server.server as srv
        from mcp_server.server import AuthContext

        srv._auth = AuthContext(
            tenant_id=services["tenant_id"],
            project_id=services["project_id"],
            api_key=services["service_key"],
            user_id=None,  # 项目级 Key
        )
        srv._memory_manager = services["memory_manager"]
        srv._vector_store = services["vector_store"]
        srv._meta_store = services["meta_store"]

    def test_add_memory_with_user_id(self, services):
        """项目级 Key：显式传 user_id"""
        self._bind_context(services)
        from mcp_server.server import add_memory

        result = add_memory(
            user_id="u1",
            content="喜欢安静的环境",
            memory_type="preference",
        )
        data = json.loads(result)
        assert data["status"] == "success"
        assert data["content"] == "喜欢安静的环境"

    def test_add_memory_without_user_id(self, services):
        """项目级 Key：不传 user_id → 报错"""
        self._bind_context(services)
        from mcp_server.server import add_memory

        result = add_memory(content="测试", memory_type="factual")
        assert "缺少 user_id" in result

    def test_search_memory(self, services):
        """语义搜索"""
        self._bind_context(services)
        from mcp_server.server import add_memory, search_memory

        add_memory(user_id="u1", content="喜欢吃川菜", memory_type="preference")
        add_memory(user_id="u1", content="生日是 3 月 15 日", memory_type="factual")

        result = search_memory(user_id="u1", query="饮食偏好")
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_delete_memory(self, services):
        """删除记忆"""
        self._bind_context(services)
        from mcp_server.server import add_memory, delete_memory

        r = json.loads(add_memory(user_id="u1", content="待删除", memory_type="factual"))
        memory_id = r["id"]

        result = json.loads(delete_memory(user_id="u1", memory_id=memory_id))
        assert result["status"] == "success"

    def test_get_user_stats(self, services):
        """用户统计"""
        self._bind_context(services)
        from mcp_server.server import add_memory, get_user_stats

        add_memory(user_id="u1", content="事实 1", memory_type="factual")
        add_memory(user_id="u1", content="偏好 1", memory_type="preference")

        result = json.loads(get_user_stats(user_id="u1"))
        assert result["total_memories"] == 2

    def test_user_isolation(self, services):
        """不同用户数据隔离"""
        self._bind_context(services)
        from mcp_server.server import add_memory, search_memory

        add_memory(user_id="alice", content="Alice 喜欢猫", memory_type="preference")
        add_memory(user_id="bob", content="Bob 喜欢狗", memory_type="preference")

        result = search_memory(user_id="alice", query="喜欢什么动物")
        data = json.loads(result)
        for item in data:
            assert "Bob" not in item["content"]


class TestMCPToolsPersonalKey:
    """MCP Tool 功能测试（用户级 Key，C 端场景）"""

    def _bind_context(self, services):
        """绑定用户级 Key 的鉴权上下文"""
        import mcp_server.server as srv
        from mcp_server.server import AuthContext

        srv._auth = AuthContext(
            tenant_id=services["tenant_id"],
            project_id=services["project_id"],
            api_key=services["personal_key"],
            user_id="zhangsan",  # 用户级 Key
        )
        srv._memory_manager = services["memory_manager"]
        srv._vector_store = services["vector_store"]
        srv._meta_store = services["meta_store"]

    def test_add_memory_no_user_id(self, services):
        """用户级 Key：不传 user_id，自动使用绑定值"""
        self._bind_context(services)
        from mcp_server.server import add_memory

        result = add_memory(content="喜欢喝咖啡", memory_type="preference")
        data = json.loads(result)
        assert data["status"] == "success"

    def test_add_memory_override_rejected(self, services):
        """用户级 Key：传入不同的 user_id 直接返回报错"""
        self._bind_context(services)
        from mcp_server.server import add_memory

        result = add_memory(user_id="hacker", content="偏好测试", memory_type="preference")
        assert "不允许操作其他用户数据" in result

    def test_search_no_user_id(self, services):
        """用户级 Key：搜索不需要传 user_id"""
        self._bind_context(services)
        from mcp_server.server import add_memory, search_memory

        add_memory(content="喜欢爬山", memory_type="preference")
        result = search_memory(query="运动偏好")
        # 不会报错，能正常返回
        assert "缺少" not in result

    def test_message_and_history(self, services):
        """用户级 Key：会话消息不需要传 user_id"""
        self._bind_context(services)
        from mcp_server.server import add_message, get_history
        import time

        r1 = add_message(content="你好", role="user", session_id="s1")
        assert json.loads(r1)["status"] == "success"

        time.sleep(0.01)

        r2 = add_message(content="你好！", role="assistant", session_id="s1")
        assert json.loads(r2)["status"] == "success"

        result = get_history(session_id="s1")
        messages = json.loads(result)
        assert len(messages) == 2


class TestMCPToolsEnvVar:
    """ENGRAMA_USER_ID 环境变量测试"""

    def _bind_context_with_env(self, services, env_user_id):
        """绑定项目级 Key + ENGRAMA_USER_ID 的上下文"""
        import mcp_server.server as srv
        from mcp_server.server import AuthContext

        srv._auth = AuthContext(
            tenant_id=services["tenant_id"],
            project_id=services["project_id"],
            api_key=services["service_key"],
            user_id=None,  # 项目级 Key
            default_user_id=env_user_id,
        )
        srv._memory_manager = services["memory_manager"]
        srv._vector_store = services["vector_store"]
        srv._meta_store = services["meta_store"]

    def test_env_var_as_default(self, services):
        """ENGRAMA_USER_ID 作为默认 user_id"""
        self._bind_context_with_env(services, "env_user")
        from mcp_server.server import add_memory, get_user_stats

        # 不传 user_id，使用环境变量默认值
        result = add_memory(content="来自环境变量", memory_type="factual")
        data = json.loads(result)
        assert data["status"] == "success"

        stats = json.loads(get_user_stats())  # 不传 user_id
        assert stats["user_id"] == "env_user"

    def test_explicit_overrides_env(self, services):
        """显式传入 user_id 优先于环境变量"""
        self._bind_context_with_env(services, "env_user")
        from mcp_server.server import add_memory, get_user_stats

        add_memory(user_id="explicit_user", content="显式用户", memory_type="factual")

        stats = json.loads(get_user_stats(user_id="explicit_user"))
        assert stats["total_memories"] == 1


class TestMCPToolResolverEdgeCases:
    """user_id 解析边界情况测试"""

    def test_all_empty_rejected(self, services):
        """没有任何 user_id 来源时报错"""
        import mcp_server.server as srv
        from mcp_server.server import AuthContext, add_memory

        srv._auth = AuthContext(
            tenant_id=services["tenant_id"],
            project_id=services["project_id"],
            api_key=services["service_key"],
            user_id=None,
            default_user_id=None,
        )

        result = add_memory(user_id="", content="无来源", memory_type="factual")
        assert "缺少 user_id" in result


class TestMCPToolSignature:
    """Tool 签名验证"""

    def test_no_tenant_project_params(self, services):
        """Tool 签名中不包含 tenant_id 和 project_id"""
        import inspect
        from mcp_server.server import (
            add_memory, search_memory, add_message,
            get_history, delete_memory, get_user_stats,
        )

        for tool_fn in [add_memory, search_memory, add_message,
                        get_history, delete_memory, get_user_stats]:
            params = inspect.signature(tool_fn).parameters
            assert "tenant_id" not in params, \
                f"{tool_fn.__name__} 不应暴露 tenant_id"
            assert "project_id" not in params, \
                f"{tool_fn.__name__} 不应暴露 project_id"

    def test_user_id_optional(self, services):
        """所有 Tool 的 user_id 参数有默认值（可选）"""
        import inspect
        from mcp_server.server import (
            add_memory, search_memory, add_message,
            get_history, delete_memory, get_user_stats,
        )

        for tool_fn in [add_memory, search_memory, add_message,
                        get_history, delete_memory, get_user_stats]:
            params = inspect.signature(tool_fn).parameters
            if "user_id" in params:
                assert params["user_id"].default == "", \
                    f"{tool_fn.__name__} 的 user_id 应有空字符串默认值"
