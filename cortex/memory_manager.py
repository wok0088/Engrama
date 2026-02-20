"""
记忆管理器

面向业务的高层 API，组合 VectorStore 和 MetaStore 的底层操作。
提供记忆的添加、搜索、历史查询、列举、删除和统计功能。
"""

from typing import Optional

from cortex.models import MemoryFragment, MemoryType, Role
from cortex.store.vector_store import VectorStore
from cortex.store.meta_store import MetaStore


class MemoryManager:
    """
    记忆管理器 — Cortex 的核心业务层

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
        """
        初始化记忆管理器

        Args:
            vector_store: 向量存储实例，默认自动创建
            meta_store: 元数据存储实例，默认自动创建
        """
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
        """
        添加记忆片段

        Args:
            tenant_id: 租户 ID
            project_id: 项目 ID
            user_id: 用户 ID
            content: 记忆内容
            memory_type: 记忆类型
            role: 消息角色（仅 session 类型）
            session_id: 会话 ID（仅 session 类型）
            tags: 标签列表
            importance: 重要度评分
            metadata: 扩展元数据

        Returns:
            创建的 MemoryFragment 对象
        """
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
        """
        添加会话消息 — session 类型的快捷方法

        Args:
            tenant_id: 租户 ID
            project_id: 项目 ID
            user_id: 用户 ID
            content: 消息内容
            role: 消息角色（user / assistant / system）
            session_id: 会话 ID
            metadata: 扩展元数据

        Returns:
            创建的 MemoryFragment 对象
        """
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

        搜索结果按语义相似度排序，每个结果包含 score 字段（0-1，越大越相似）。
        搜索会自动增加被命中记忆的 hit_count。

        Args:
            tenant_id: 租户 ID
            project_id: 项目 ID
            user_id: 用户 ID
            query: 搜索查询文本
            limit: 返回数量上限
            memory_type: 按类型过滤
            session_id: 按会话过滤

        Returns:
            搜索结果列表
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
                pass  # hit_count 更新失败不影响搜索结果

        return results

    def get_history(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        session_id: str,
        limit: int = 100,
    ) -> list[dict]:
        """
        获取会话历史（按时间排序）

        Args:
            tenant_id: 租户 ID
            project_id: 项目 ID
            user_id: 用户 ID
            session_id: 会话 ID
            limit: 返回数量上限

        Returns:
            按时间排序的消息列表
        """
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
        """
        获取 LLM 兼容格式的会话历史

        返回格式直接兼容 OpenAI / Anthropic 的 messages 参数。

        Returns:
            [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
        """
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
        """
        列出记忆片段

        Args:
            tenant_id: 租户 ID
            project_id: 项目 ID
            user_id: 用户 ID
            memory_type: 按类型过滤
            limit: 返回数量上限

        Returns:
            记忆片段列表
        """
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
        """
        删除指定记忆片段

        Args:
            tenant_id: 租户 ID
            project_id: 项目 ID
            user_id: 用户 ID
            fragment_id: 记忆片段 ID

        Returns:
            是否成功删除
        """
        return self._vector_store.delete(
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            fragment_id=fragment_id,
        )

    def get_stats(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
    ) -> dict:
        """
        获取用户记忆统计信息

        Returns:
            包含总数和按类型统计的字典
        """
        stats = self._vector_store.get_stats(tenant_id, project_id, user_id)
        stats["user_id"] = user_id
        return stats
