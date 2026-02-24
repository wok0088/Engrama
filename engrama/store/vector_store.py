"""
ChromaDB 向量存储

封装所有与 ChromaDB 交互的底层操作，提供记忆片段的向量化存储和语义搜索。

Collection 策略（v0.2.1）：
  - 按 Project 划分 Collection：{tenant_id}__{project_id}
  - 用户隔离通过 metadata 中的 user_id 字段进行 where 过滤
  - 同一 Project 下的所有用户共享一个 Collection，避免海量 Collection 问题

默认使用 BAAI/bge-m3 多语言 Embedding 模型，
可通过环境变量 ENGRAMA_EMBEDDING_MODEL 切换。
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

import chromadb
from chromadb.config import Settings
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from engrama import config
from engrama.logger import get_logger
from engrama.models import MemoryFragment, MemoryType

from engrama.store import create_meta_store
from engrama.store.base_meta_store import BaseMetaStore

logger = get_logger(__name__)


class VectorStore:
    """
    ChromaDB 向量存储

    每个 tenant/project 组合对应一个 Collection，
    用户隔离通过 metadata 的 where 过滤实现。
    """

    def __init__(self, persist_directory: Optional[str] = None, meta_store: Optional[BaseMetaStore] = None):
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
        self._meta_store = meta_store or create_meta_store()

    # ----------------------------------------------------------
    # 内部工具方法
    # ----------------------------------------------------------

    @staticmethod
    def _collection_name(tenant_id: str, project_id: str) -> str:
        """
        生成 Collection 名称（按 Project 粒度）

        格式：{tenant_id}__{project_id}
        ChromaDB 要求名称 3-63 字符、仅字母数字下划线和点号。
        超过 63 字符时截断并附加 MD5 哈希后缀防止冲突。
        """
        def _sanitize(s: str) -> str:
            return re.sub(r"[^a-zA-Z0-9_]", "_", s)

        name = f"{_sanitize(tenant_id)}__{_sanitize(project_id)}"
        if len(name) > 63:
            hash_suffix = hashlib.sha256(name.encode()).hexdigest()[:8]
            name = f"{name[:54]}_{hash_suffix}"
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
        """将 MemoryFragment 的最少字段打包为 ChromaDB metadata（防丢记录）"""
        meta = {
            "fragment_id": fragment.id,
            "tenant_id": fragment.tenant_id,
            "project_id": fragment.project_id,
            "user_id": fragment.user_id,
            "memory_type": fragment.memory_type.value,
            "created_at": fragment.created_at.isoformat(),
        }
        if fragment.session_id is not None:
            meta["session_id"] = fragment.session_id
        return meta

    def _enrich_with_meta_store(self, items: list[dict], with_score: bool = False) -> list[dict]:
        """将 ChromaDB 返回的极简项补全 MetaStore 中的结构化元数据"""
        if not items:
            return []

        fragment_ids = [item["id"] for item in items]
        metas = self._meta_store.get_memory_fragments(fragment_ids)
        meta_map = {m["id"]: m for m in metas}

        enriched = []
        for item in items:
            fid = item["id"]
            if fid not in meta_map:
                continue

            full_data = meta_map[fid]
            # 覆盖内容，ChromaDB为主，保留score
            full_data["content"] = item["content"]
            if with_score and "score" in item:
                full_data["score"] = item["score"]
            enriched.append(full_data)
        return enriched

    def _metadata_to_base_dict(self, meta: dict, content: str, score: Optional[float] = None) -> dict:
        """将 ChromaDB 极简 metadata 转为基础字典（供后续拼装）"""
        result = {
            "id": meta.get("fragment_id", ""),
            "content": content,
        }
        if score is not None:
            result["score"] = score
        return result

    # ----------------------------------------------------------
    # 公开 API
    # ----------------------------------------------------------

    def add(self, fragment: MemoryFragment) -> None:
        """添加记忆片段到向量数据库（双写到关系型DB）"""
        self._meta_store.add_memory_fragment(fragment)

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

        results = collection.query(
            query_texts=[query],
            n_results=limit,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        items = []
        if results and results["ids"] and results["ids"][0]:
            for i, _id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i]
                score = 1.0 / (1.0 + distance)
                items.append(
                    self._metadata_to_base_dict(
                        results["metadatas"][0][i],
                        results["documents"][0][i],
                        score=score,
                    )
                )

        enriched_items = self._enrich_with_meta_store(items, with_score=True)

        logger.debug("搜索完成: user=%s, query='%s', 结果=%d", user_id, query[:50], len(enriched_items))
        return enriched_items

    def get_by_session(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """获取指定会话的所有消息（按创建时间排序）"""
        collection = self._get_collection(tenant_id, project_id)

        if collection.count() == 0:
            return []

        where = self._build_where(user_id=user_id, session_id=session_id)

        results = collection.get(
            where=where,
            limit=limit,
            offset=offset,
            include=["documents", "metadatas"],
        )

        items = []
        if results and results["ids"]:
            for i, _id in enumerate(results["ids"]):
                items.append(
                    self._metadata_to_base_dict(
                        results["metadatas"][i], results["documents"][i]
                    )
                )

        enriched_items = self._enrich_with_meta_store(items)
        enriched_items.sort(key=lambda x: x.get("created_at", ""))
        return enriched_items

    def list_memories(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        memory_type: Optional[MemoryType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """列出记忆片段（按 user_id 过滤）"""
        collection = self._get_collection(tenant_id, project_id)

        if collection.count() == 0:
            return []

        where = self._build_where(user_id=user_id, memory_type=memory_type)

        results = collection.get(
            where=where,
            limit=limit,
            offset=offset,
            include=["documents", "metadatas"],
        )

        items = []
        if results and results["ids"]:
            for i, _id in enumerate(results["ids"]):
                items.append(
                    self._metadata_to_base_dict(
                        results["metadatas"][i], results["documents"][i]
                    )
                )

        enriched_items = self._enrich_with_meta_store(items)
        enriched_items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return enriched_items

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
        更新记忆片段（双写更新关系型 DB 和 Vector Store）

        Returns:
            更新后的记忆字典，不存在则返回 None
        """
        # 更新关系型 DB
        updates = {}
        if content is not None:
            updates["content"] = content
        if tags is not None:
            updates["tags"] = tags
        if importance is not None:
            updates["importance"] = importance
        if metadata is not None:
            updates["metadata"] = metadata

        success = self._meta_store.update_memory_fragment(fragment_id, updates)
        if not success:
            return None

        # 更新 ChromaDB
        collection = self._get_collection(tenant_id, project_id)
        results = collection.get(ids=[fragment_id], include=["metadatas", "documents"])

        if not results or not results["ids"]:
            return None

        # 验证 user_id 归属
        old_meta = results["metadatas"][0]
        if old_meta.get("user_id") != user_id:
            return None

        old_content = results["documents"][0]
        new_content = content if content is not None else old_content

        update_kwargs = {"ids": [fragment_id]}
        if content is not None:
            update_kwargs["documents"] = [new_content]

        # ChromaDB 中只需更新内容，元数据使用最简集
        if content is not None:
            collection.update(**update_kwargs)

        logger.debug("更新记忆: id=%s", fragment_id)

        # 返回完整最新数据
        full_data = self._meta_store.get_memory_fragment(fragment_id)
        return full_data

    def delete(self, tenant_id: str, project_id: str, user_id: str, fragment_id: str) -> bool:
        """删除指定记忆片段（同时删除 Vector Store 和 关系型 DB）"""
        # 从元数据存储删除
        success = self._meta_store.delete_memory_fragment(fragment_id)
        if not success:
            return False

        collection = self._get_collection(tenant_id, project_id)
        try:
            # 在 ChromaDB 中直接删除，不报错（忽略不存在）
            collection.delete(ids=[fragment_id])
            logger.debug("删除记忆: id=%s", fragment_id)
            return True
        except Exception:
            return False

    def get_stats(self, tenant_id: str, project_id: str, user_id: str) -> dict:
        """
        获取指定用户的统计信息

        现在完全从关系型 DB 获取，避免了 ChromaDB 查询所有数据带来的 OOM 问题。
        """
        return self._meta_store.get_user_stats(tenant_id, project_id, user_id)

    def increment_hit_count(
        self, tenant_id: str, project_id: str, user_id: str, fragment_id: str
    ) -> None:
        """
        增加记忆片段的检索命中次数

        现在完全依赖关系型 DB，支持高并发，避免了竞态条件和写入冲突。
        """
        self._meta_store.increment_hit_count(fragment_id)

    def batch_increment_hit_count(
        self, tenant_id: str, project_id: str, fragment_ids: list[str]
    ) -> None:
        """
        批量增加记忆片段的检索命中次数
        """
        self._meta_store.batch_increment_hit_count(fragment_ids)

    def delete_collection(self, tenant_id: str, project_id: str) -> None:
        """删除整个项目的 ChromaDB Collection"""
        name = self._collection_name(tenant_id, project_id)
        try:
            self._client.delete_collection(name)
            logger.info("已删除 ChromaDB Collection: %s", name)
        except Exception as e:
            logger.warning("删除 ChromaDB Collection 失败或不存在: %s, 错误: %s", name, e)

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
