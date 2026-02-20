"""
ChromaDB 向量存储

封装所有与 ChromaDB 交互的底层操作，提供记忆片段的向量化存储和语义搜索。
Collection 命名规则：{tenant_id}__{project_id}__{user_id}，确保三层数据隔离。
"""

import os
from typing import Optional

import chromadb
from chromadb.config import Settings

from cortex import config
from cortex.models import MemoryFragment, MemoryType


class VectorStore:
    """
    ChromaDB 向量存储

    每个 tenant/project/user 组合对应一个独立的 Collection，
    确保数据在三层结构上的完全隔离。
    """

    def __init__(self, persist_directory: Optional[str] = None):
        """
        初始化 ChromaDB 客户端

        Args:
            persist_directory: 数据持久化目录，默认使用配置值
        """
        persist_dir = persist_directory or str(config.CHROMA_PERSIST_DIR)
        os.makedirs(persist_dir, exist_ok=True)

        self._client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )

    # ----------------------------------------------------------
    # 内部工具方法
    # ----------------------------------------------------------

    @staticmethod
    def _collection_name(tenant_id: str, project_id: str, user_id: str) -> str:
        """
        生成 Collection 名称

        格式：{tenant_id}__{project_id}__{user_id}
        ChromaDB 要求名称 3-63 字符、仅字母数字下划线和点号。
        """
        def _sanitize(s: str) -> str:
            return s.replace("-", "_").replace("@", "_at_")

        name = f"{_sanitize(tenant_id)}__{_sanitize(project_id)}__{_sanitize(user_id)}"
        # 确保名称在合法范围内（截断至 63 字符）
        if len(name) > 63:
            name = name[:63]
        return name

    def _get_collection(self, tenant_id: str, project_id: str, user_id: str):
        """获取或创建指定用户的 Collection"""
        name = self._collection_name(tenant_id, project_id, user_id)
        return self._client.get_or_create_collection(name=name)

    @staticmethod
    def _fragment_to_metadata(fragment: MemoryFragment) -> dict:
        """将 MemoryFragment 的字段打包为 ChromaDB metadata"""
        meta = {
            "fragment_id": fragment.id,
            "tenant_id": fragment.tenant_id,
            "project_id": fragment.project_id,
            "user_id": fragment.user_id,
            "memory_type": fragment.memory_type.value,
            "hit_count": fragment.hit_count,
            "importance": fragment.importance,
            "created_at": fragment.created_at.isoformat(),
            "updated_at": fragment.updated_at.isoformat(),
        }
        if fragment.role is not None:
            meta["role"] = fragment.role.value
        if fragment.session_id is not None:
            meta["session_id"] = fragment.session_id
        if fragment.tags:
            # ChromaDB metadata 不支持 list，用逗号分隔存储
            meta["tags"] = ",".join(fragment.tags)
        if fragment.metadata:
            # 扩展元数据序列化为字符串存储
            import json
            meta["extra_metadata"] = json.dumps(fragment.metadata, ensure_ascii=False)
        return meta

    @staticmethod
    def _metadata_to_dict(meta: dict, content: str, score: Optional[float] = None) -> dict:
        """将 ChromaDB metadata 转为通用字典"""
        import json
        result = {
            "id": meta.get("fragment_id", ""),
            "tenant_id": meta.get("tenant_id", ""),
            "project_id": meta.get("project_id", ""),
            "user_id": meta.get("user_id", ""),
            "content": content,
            "memory_type": meta.get("memory_type", ""),
            "role": meta.get("role"),
            "session_id": meta.get("session_id"),
            "tags": meta.get("tags", "").split(",") if meta.get("tags") else [],
            "hit_count": meta.get("hit_count", 0),
            "importance": meta.get("importance", 0.0),
            "created_at": meta.get("created_at", ""),
            "updated_at": meta.get("updated_at", ""),
            "metadata": json.loads(meta["extra_metadata"]) if meta.get("extra_metadata") else None,
        }
        if score is not None:
            result["score"] = score
        return result

    # ----------------------------------------------------------
    # 公开 API
    # ----------------------------------------------------------

    def add(self, fragment: MemoryFragment) -> None:
        """
        添加记忆片段到向量数据库

        Args:
            fragment: 记忆片段对象
        """
        collection = self._get_collection(
            fragment.tenant_id, fragment.project_id, fragment.user_id
        )
        collection.add(
            ids=[fragment.id],
            documents=[fragment.content],
            metadatas=[self._fragment_to_metadata(fragment)],
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

        Args:
            tenant_id: 租户 ID
            project_id: 项目 ID
            user_id: 用户 ID
            query: 搜索查询文本
            limit: 返回数量上限
            memory_type: 按类型过滤
            session_id: 按会话过滤

        Returns:
            按相似度排序的结果列表
        """
        collection = self._get_collection(tenant_id, project_id, user_id)

        # 如果 Collection 为空，直接返回
        if collection.count() == 0:
            return []

        # 构建过滤条件
        where = self._build_where(memory_type=memory_type, session_id=session_id)

        # 限制 limit 不超过 collection 中的文档数量
        actual_limit = min(limit, collection.count())

        results = collection.query(
            query_texts=[query],
            n_results=actual_limit,
            where=where if where else None,
            include=["documents", "metadatas", "distances"],
        )

        items = []
        if results and results["ids"] and results["ids"][0]:
            for i, _id in enumerate(results["ids"][0]):
                # ChromaDB 的 distance 越小越相似，转换为 score（越大越相似）
                distance = results["distances"][0][i]
                score = 1.0 / (1.0 + distance)
                items.append(
                    self._metadata_to_dict(
                        results["metadatas"][0][i],
                        results["documents"][0][i],
                        score=score,
                    )
                )
        return items

    def get_by_session(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        session_id: str,
        limit: int = 100,
    ) -> list[dict]:
        """
        获取指定会话的所有消息

        Args:
            tenant_id: 租户 ID
            project_id: 项目 ID
            user_id: 用户 ID
            session_id: 会话 ID
            limit: 返回数量上限

        Returns:
            按创建时间排序的消息列表
        """
        collection = self._get_collection(tenant_id, project_id, user_id)

        if collection.count() == 0:
            return []

        results = collection.get(
            where={"session_id": session_id},
            limit=limit,
            include=["documents", "metadatas"],
        )

        items = []
        if results and results["ids"]:
            for i, _id in enumerate(results["ids"]):
                items.append(
                    self._metadata_to_dict(
                        results["metadatas"][i], results["documents"][i]
                    )
                )

        # 按创建时间排序
        items.sort(key=lambda x: x.get("created_at", ""))
        return items

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
        collection = self._get_collection(tenant_id, project_id, user_id)

        if collection.count() == 0:
            return []

        where = self._build_where(memory_type=memory_type)
        results = collection.get(
            where=where if where else None,
            limit=limit,
            include=["documents", "metadatas"],
        )

        items = []
        if results and results["ids"]:
            for i, _id in enumerate(results["ids"]):
                items.append(
                    self._metadata_to_dict(
                        results["metadatas"][i], results["documents"][i]
                    )
                )

        # 按创建时间降序
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return items

    def delete(self, tenant_id: str, project_id: str, user_id: str, fragment_id: str) -> bool:
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
        collection = self._get_collection(tenant_id, project_id, user_id)
        try:
            collection.delete(ids=[fragment_id])
            return True
        except Exception:
            return False

    def get_stats(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
    ) -> dict:
        """
        获取统计信息

        Returns:
            包含总数和按类型统计的字典
        """
        collection = self._get_collection(tenant_id, project_id, user_id)
        total = collection.count()

        by_type: dict[str, int] = {}
        if total > 0:
            results = collection.get(include=["metadatas"])
            if results and results["metadatas"]:
                for meta in results["metadatas"]:
                    mt = meta.get("memory_type", "unknown")
                    by_type[mt] = by_type.get(mt, 0) + 1

        return {"total": total, "by_type": by_type}

    def increment_hit_count(
        self, tenant_id: str, project_id: str, user_id: str, fragment_id: str
    ) -> None:
        """增加记忆片段的检索命中次数"""
        collection = self._get_collection(tenant_id, project_id, user_id)
        results = collection.get(ids=[fragment_id], include=["metadatas", "documents"])
        if results and results["ids"]:
            meta = results["metadatas"][0]
            meta["hit_count"] = meta.get("hit_count", 0) + 1
            collection.update(
                ids=[fragment_id],
                metadatas=[meta],
            )

    # ----------------------------------------------------------
    # 私有辅助
    # ----------------------------------------------------------

    @staticmethod
    def _build_where(
        memory_type: Optional[MemoryType] = None,
        session_id: Optional[str] = None,
    ) -> Optional[dict]:
        """构建 ChromaDB where 过滤条件"""
        conditions = []
        if memory_type is not None:
            conditions.append({"memory_type": memory_type.value})
        if session_id is not None:
            conditions.append({"session_id": session_id})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}
