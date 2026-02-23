"""
记忆管理器

面向业务的高层 API，组合 VectorStore 和 MetaStore 的底层操作。
提供记忆的添加、更新、搜索、历史查询、列举、删除和统计功能。
"""

from typing import Optional

from cortex.logger import get_logger
from cortex.models import MemoryFragment, MemoryType, Role
from cortex.store.vector_store import VectorStore
from cortex.store.meta_store import MetaStore

logger = get_logger(__name__)


class MemoryManager:
    """
    记忆管理器 — Engrama 的核心业务层

    使用示例：
    ```python
    from cortex.memory_manager import MemoryManager

    manager = MemoryManager()

    # 添加事实记忆
    manager.add(
        tenant_id="t1", project_id="p1", user_id="u1",
        content="生日是 1990-03-15",
        memory_type=MemoryType.FACTUAL,
    )

    # 语义搜索
    results = manager.search(
        tenant_id="t1", project_id="p1", user_id="u1",
        query="生日",
    )
    ```
    """

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        meta_store: Optional[MetaStore] = None,
    ):
        self._vector_store = vector_store or VectorStore()
        self._meta_store = meta_store or MetaStore()

    # ----------------------------------------------------------
    # 核心 API
    # ----------------------------------------------------------

    def add(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        content: str,
        memory_type: MemoryType,
        role: Optional[Role] = None,
        session_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        importance: float = 0.0,
        metadata: Optional[dict] = None,
    ) -> MemoryFragment:
        """添加记忆片段"""
        fragment = MemoryFragment(
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            content=content,
            memory_type=memory_type,
            role=role,
            session_id=session_id,
            tags=tags or [],
            importance=importance,
            metadata=metadata,
        )
        self._vector_store.add(fragment)
        logger.info(
            "添加记忆: user=%s, type=%s, id=%s",
            user_id, memory_type.value, fragment.id,
        )
        return fragment

    def add_message(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        content: str,
        role: Role,
        session_id: str,
        metadata: Optional[dict] = None,
    ) -> MemoryFragment:
        """添加会话消息 — session 类型的快捷方法"""
        return self.add(
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            content=content,
            memory_type=MemoryType.SESSION,
            role=role,
            session_id=session_id,
            metadata=metadata,
        )

    def search(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        query: str,
        limit: int = 10,
        memory_type: Optional[MemoryType] = None,
        session_id: Optional[str] = None,
    ) -> list[dict]:
        """
        语义搜索记忆

        搜索结果按语义相似度排序，搜索会自动增加被命中记忆的 hit_count。
        """
        results = self._vector_store.search(
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            query=query,
            limit=limit,
            memory_type=memory_type,
            session_id=session_id,
        )

        # 更新被命中记忆的 hit_count
        for item in results:
            try:
                self._vector_store.increment_hit_count(
                    tenant_id, project_id, user_id, item["id"]
                )
            except Exception:
                pass

        logger.info("搜索记忆: user=%s, query='%s', 结果=%d", user_id, query[:50], len(results))
        return results

    def update(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        fragment_id: str,
        content: Optional[str] = None,
        tags: Optional[list[str]] = None,
        importance: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[dict]:
        """
        更新记忆片段

        只更新传入的非 None 字段。如果更新了 content，会自动重新向量化。

        Returns:
            更新后的记忆字典，不存在则返回 None
        """
        result = self._vector_store.update(
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            fragment_id=fragment_id,
            content=content,
            tags=tags,
            importance=importance,
            metadata=metadata,
        )
        if result:
            logger.info("更新记忆: id=%s, user=%s", fragment_id, user_id)
        return result

    def get_history(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        session_id: str,
        limit: int = 100,
    ) -> list[dict]:
        """获取会话历史（按时间排序）"""
        return self._vector_store.get_by_session(
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            session_id=session_id,
            limit=limit,
        )

    def get_history_for_llm(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        session_id: str,
        limit: int = 50,
    ) -> list[dict]:
        """获取 LLM 兼容格式的会话历史"""
        history = self.get_history(
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            session_id=session_id,
            limit=limit,
        )
        return [
            {"role": item.get("role", "user"), "content": item["content"]}
            for item in history
        ]

    def list_memories(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        memory_type: Optional[MemoryType] = None,
        limit: int = 100,
    ) -> list[dict]:
        """列出记忆片段"""
        return self._vector_store.list_memories(
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            memory_type=memory_type,
            limit=limit,
        )

    def delete(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        fragment_id: str,
    ) -> bool:
        """删除指定记忆片段"""
        success = self._vector_store.delete(
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            fragment_id=fragment_id,
        )
        if success:
            logger.info("删除记忆: id=%s, user=%s", fragment_id, user_id)
        return success

    def get_stats(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
    ) -> dict:
        """获取用户记忆统计信息"""
        stats = self._vector_store.get_stats(tenant_id, project_id, user_id)
        stats["user_id"] = user_id
        return stats
