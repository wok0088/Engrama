"""
ChromaDB 向量存储

封装所有与 ChromaDB 交互的底层操作，提供记忆片段的向量化存储和语义搜索。

Collection 策略（v0.2.1）：
  - 按 Project 划分 Collection：{tenant_id}__{project_id}
  - 用户隔离通过 metadata 中的 user_id 字段进行 where 过滤
  - 同一 Project 下的所有用户共享一个 Collection，避免海量 Collection 问题

默认使用 BAAI/bge-small-zh-v1.5 中文 Embedding 模型，
可通过环境变量 CORTEX_EMBEDDING_MODEL 切换。
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

import chromadb
from chromadb.config import Settings
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from cortex import config
from cortex.logger import get_logger
from cortex.models import MemoryFragment, MemoryType

logger = get_logger(__name__)


class VectorStore:
    """
    ChromaDB 向量存储

    每个 tenant/project 组合对应一个 Collection，
    用户隔离通过 metadata 的 where 过滤实现。
    """

    def __init__(self, persist_directory: Optional[str] = None):
        """
        初始化 ChromaDB 客户端和 Embedding 模型

        Args:
            persist_directory: 数据持久化目录，默认使用配置值
        """
        persist_dir = persist_directory or str(config.CHROMA_PERSIST_DIR)
        os.makedirs(persist_dir, exist_ok=True)

        self._client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )

        # 初始化 Embedding 函数
        model_name = config.EMBEDDING_MODEL
        logger.info("加载 Embedding 模型: %s", model_name)
        self._embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name=model_name,
        )
        logger.info("Embedding 模型加载完成")

    # ----------------------------------------------------------
    # 内部工具方法
    # ----------------------------------------------------------

    @staticmethod
    def _collection_name(tenant_id: str, project_id: str) -> str:
        """
        生成 Collection 名称（按 Project 粒度）

        格式：{tenant_id}__{project_id}
        ChromaDB 要求名称 3-63 字符、仅字母数字下划线和点号。
        """
        def _sanitize(s: str) -> str:
            return s.replace("-", "_").replace("@", "_at_")

        name = f"{_sanitize(tenant_id)}__{_sanitize(project_id)}"
        if len(name) > 63:
            name = name[:63]
        return name

    def _get_collection(self, tenant_id: str, project_id: str):
        """获取或创建指定项目的 Collection（使用自定义 Embedding 函数）"""
        name = self._collection_name(tenant_id, project_id)
        return self._client.get_or_create_collection(
            name=name,
            embedding_function=self._embedding_fn,
        )

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
            meta["tags"] = ",".join(fragment.tags)
        if fragment.metadata:
            meta["extra_metadata"] = json.dumps(fragment.metadata, ensure_ascii=False)
        return meta

    @staticmethod
    def _metadata_to_dict(meta: dict, content: str, score: Optional[float] = None) -> dict:
        """将 ChromaDB metadata 转为通用字典"""
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
        """添加记忆片段到向量数据库"""
        collection = self._get_collection(fragment.tenant_id, fragment.project_id)
        collection.add(
            ids=[fragment.id],
            documents=[fragment.content],
            metadatas=[self._fragment_to_metadata(fragment)],
        )
        logger.debug("添加记忆: id=%s, user=%s, type=%s", fragment.id, fragment.user_id, fragment.memory_type.value)

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
        """语义搜索记忆（在 user_id 范围内搜索）"""
        collection = self._get_collection(tenant_id, project_id)

        if collection.count() == 0:
            return []

        # 构建 where 过滤：必须包含 user_id
        where = self._build_where(user_id=user_id, memory_type=memory_type, session_id=session_id)

        # 限制 limit 不超过 collection 中的文档数量
        actual_limit = min(limit, collection.count())

        results = collection.query(
            query_texts=[query],
            n_results=actual_limit,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        items = []
        if results and results["ids"] and results["ids"][0]:
            for i, _id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i]
                score = 1.0 / (1.0 + distance)
                items.append(
                    self._metadata_to_dict(
                        results["metadatas"][0][i],
                        results["documents"][0][i],
                        score=score,
                    )
                )

        logger.debug("搜索完成: user=%s, query='%s', 结果=%d", user_id, query[:50], len(items))
        return items

    def get_by_session(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        session_id: str,
        limit: int = 100,
    ) -> list[dict]:
        """获取指定会话的所有消息（按创建时间排序）"""
        collection = self._get_collection(tenant_id, project_id)

        if collection.count() == 0:
            return []

        where = self._build_where(user_id=user_id, session_id=session_id)

        results = collection.get(
            where=where,
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
        """列出记忆片段（按 user_id 过滤）"""
        collection = self._get_collection(tenant_id, project_id)

        if collection.count() == 0:
            return []

        where = self._build_where(user_id=user_id, memory_type=memory_type)

        results = collection.get(
            where=where,
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

        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return items

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

        Returns:
            更新后的记忆字典，不存在则返回 None
        """
        collection = self._get_collection(tenant_id, project_id)
        results = collection.get(ids=[fragment_id], include=["metadatas", "documents"])

        if not results or not results["ids"]:
            return None

        # 验证 user_id 归属
        old_meta = results["metadatas"][0]
        if old_meta.get("user_id") != user_id:
            return None

        old_content = results["documents"][0]

        # 更新 metadata
        new_meta = dict(old_meta)
        new_meta["updated_at"] = datetime.now(timezone.utc).isoformat()

        if tags is not None:
            new_meta["tags"] = ",".join(tags) if tags else ""
        if importance is not None:
            new_meta["importance"] = importance
        if metadata is not None:
            new_meta["extra_metadata"] = json.dumps(metadata, ensure_ascii=False)

        new_content = content if content is not None else old_content

        update_kwargs = {"ids": [fragment_id], "metadatas": [new_meta]}
        if content is not None:
            update_kwargs["documents"] = [new_content]
        collection.update(**update_kwargs)

        logger.debug("更新记忆: id=%s", fragment_id)
        return self._metadata_to_dict(new_meta, new_content)

    def delete(self, tenant_id: str, project_id: str, user_id: str, fragment_id: str) -> bool:
        """删除指定记忆片段"""
        collection = self._get_collection(tenant_id, project_id)
        try:
            # 验证归属后删除
            results = collection.get(ids=[fragment_id], include=["metadatas"])
            if not results or not results["ids"]:
                return False
            if results["metadatas"][0].get("user_id") != user_id:
                return False
            collection.delete(ids=[fragment_id])
            logger.debug("删除记忆: id=%s", fragment_id)
            return True
        except Exception:
            return False

    def get_stats(self, tenant_id: str, project_id: str, user_id: str) -> dict:
        """获取指定用户的统计信息"""
        collection = self._get_collection(tenant_id, project_id)

        # 按 user_id 过滤获取该用户的记忆
        where = {"user_id": user_id}
        results = collection.get(where=where, include=["metadatas"])

        total = len(results["ids"]) if results and results["ids"] else 0
        by_type: dict[str, int] = {}
        if results and results["metadatas"]:
            for meta in results["metadatas"]:
                mt = meta.get("memory_type", "unknown")
                by_type[mt] = by_type.get(mt, 0) + 1

        return {"total": total, "by_type": by_type}

    def increment_hit_count(
        self, tenant_id: str, project_id: str, user_id: str, fragment_id: str
    ) -> None:
        """增加记忆片段的检索命中次数"""
        collection = self._get_collection(tenant_id, project_id)
        results = collection.get(ids=[fragment_id], include=["metadatas", "documents"])
        if results and results["ids"]:
            meta = results["metadatas"][0]
            meta["hit_count"] = meta.get("hit_count", 0) + 1
            collection.update(ids=[fragment_id], metadatas=[meta])

    # ----------------------------------------------------------
    # 私有辅助
    # ----------------------------------------------------------

    @staticmethod
    def _build_where(
        user_id: Optional[str] = None,
        memory_type: Optional[MemoryType] = None,
        session_id: Optional[str] = None,
    ) -> Optional[dict]:
        """构建 ChromaDB where 过滤条件（始终包含 user_id）"""
        conditions = []
        if user_id is not None:
            conditions.append({"user_id": user_id})
        if memory_type is not None:
            conditions.append({"memory_type": memory_type.value})
        if session_id is not None:
            conditions.append({"session_id": session_id})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}
