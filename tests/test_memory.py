"""
记忆管理器测试

测试 MemoryManager 的核心业务方法。
"""

import os

import pytest

from engrama.models import MemoryType, Role
from engrama.store.qdrant_store import QdrantStore
from engrama.store.base_meta_store import BaseMetaStore
from engrama.store import create_meta_store
from engrama.memory_manager import MemoryManager


@pytest.fixture
def manager():
    """创建 MemoryManager 实例"""
    import engrama.config as config



    ms = create_meta_store()
    vs = QdrantStore(meta_store=ms)
    return MemoryManager(vector_store=vs, meta_store=ms)


class TestMemoryManager:
    """MemoryManager 测试用例"""

    def test_add_and_search(self, manager):
        """添加记忆后能搜索到"""
        manager.add(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="我的生日是 1990 年 3 月 15 日",
            memory_type=MemoryType.FACTUAL,
        )
        manager.add(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="我喜欢开阔安静的环境",
            memory_type=MemoryType.PREFERENCE,
        )

        results = manager.search(
            tenant_id="t1", project_id="p1", user_id="u1",
            query="生日是什么时候",
        )
        assert len(results) > 0

    def test_add_message(self, manager):
        """add_message 快捷方法"""
        fragment = manager.add_message(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="你好",
            role=Role.USER,
            session_id="s1",
        )
        assert fragment.memory_type == MemoryType.SESSION
        assert fragment.role == Role.USER
        assert fragment.session_id == "s1"

    def test_get_history(self, manager):
        """获取会话历史"""
        import time
        messages = [
            ("你好", Role.USER),
            ("你好！有什么可以帮你？", Role.ASSISTANT),
        ]
        for content, role in messages:
            time.sleep(0.01)
            manager.add_message(
                tenant_id="t1", project_id="p1", user_id="u1",
                content=content, role=role, session_id="s1",
            )

        history = manager.get_history(
            tenant_id="t1", project_id="p1", user_id="u1",
            session_id="s1",
        )
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    def test_get_history_for_llm(self, manager):
        """获取 LLM 兼容格式"""
        import time
        for content, role in [("你好", Role.USER), ("你好！", Role.ASSISTANT)]:
            time.sleep(0.01)
            manager.add_message(
                tenant_id="t1", project_id="p1", user_id="u1",
                content=content, role=role, session_id="s1",
            )

        llm_history = manager.get_history_for_llm(
            tenant_id="t1", project_id="p1", user_id="u1",
            session_id="s1",
        )
        assert llm_history == [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ]

    def test_list_memories_by_type(self, manager):
        """按类型列出记忆"""
        manager.add(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="事实 1", memory_type=MemoryType.FACTUAL,
        )
        manager.add(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="偏好 1", memory_type=MemoryType.PREFERENCE,
        )

        factual = manager.list_memories(
            tenant_id="t1", project_id="p1", user_id="u1",
            memory_type=MemoryType.FACTUAL,
        )
        assert len(factual) == 1
        assert factual[0]["memory_type"] == "factual"

    def test_delete(self, manager):
        """删除记忆"""
        fragment = manager.add(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="待删除", memory_type=MemoryType.FACTUAL,
        )
        assert manager.delete("t1", "p1", "u1", fragment.id)
        results = manager.list_memories("t1", "p1", "u1")
        assert len(results) == 0

    def test_get_stats(self, manager):
        """统计信息"""
        manager.add(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="事实", memory_type=MemoryType.FACTUAL,
        )
        manager.add(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="偏好", memory_type=MemoryType.PREFERENCE,
        )

        stats = manager.get_stats("t1", "p1", "u1")
        assert stats["total"] == 2
        assert stats["user_id"] == "u1"
        assert stats["by_type"]["factual"] == 1
        assert stats["by_type"]["preference"] == 1

    def test_tags(self, manager):
        """标签功能"""
        fragment = manager.add(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="带标签的记忆",
            memory_type=MemoryType.FACTUAL,
            tags=["重要", "个人信息"],
        )
        assert fragment.tags == ["重要", "个人信息"]

        results = manager.list_memories("t1", "p1", "u1")
        assert results[0]["tags"] == ["重要", "个人信息"]
