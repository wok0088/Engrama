"""
Qdrant 向量存储

封装与 Qdrant 交互的底层操作，提供记忆片段的向量化存储和语义搜索。
集合策略：所有企业和用户的记忆默认存放在同一个 Collection 中，通过 Payload（如 tenant_id, project_id, user_id 等）进行严格的数据隔离与过滤搜索。
"""

import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
import urllib.request
import json

from engrama import config
from engrama.logger import get_logger
from engrama.models import MemoryFragment, MemoryType
from engrama.store.base_meta_store import BaseMetaStore

logger = get_logger(__name__)

# 全局共享 Collection 名称
COLLECTION_NAME = "engrama_memories"

class QdrantStore:
    """
    Qdrant 向量存储
    """

    def __init__(self, meta_store: BaseMetaStore = None):
        """
        初始化 Qdrant 客户端和 Embedding 模型配置
        """
        if meta_store is None:
            raise ValueError("meta_store is required for QdrantStore")

        self._client = QdrantClient(
            url=f"http://{config.QDRANT_HOST}:{config.QDRANT_PORT}",
            api_key=config.QDRANT_API_KEY if config.QDRANT_API_KEY else None,
        )

        self._embedding_api_url = getattr(config, "EMBEDDING_API_URL", "http://localhost:8080")
        self._embedding_api_key = getattr(config, "EMBEDDING_API_KEY", "")
        self._vector_size = getattr(config, "EMBEDDING_VECTOR_SIZE", 1024)

        self._meta_store = meta_store

        # 初始化 Qdrant 集合
        self._init_collection()

    def _encode(self, text: str) -> list[float]:
        """调用 TEI API 将文本转换为向量"""
        url = f"{self._embedding_api_url.rstrip('/')}/embed"
        headers = {"Content-Type": "application/json"}
        if self._embedding_api_key:
            headers["Authorization"] = f"Bearer {self._embedding_api_key}"
            
        data = json.dumps({"inputs": text}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode("utf-8"))
                # TEI 返回的通常是嵌套的列表: [[...]] 或 [...]
                if isinstance(result, list) and len(result) > 0:
                    if isinstance(result[0], list):
                        return result[0]
                    return result
                return []
        except Exception as e:
            logger.error(f"获取 Embedding 失败: {e}")
            raise

    def _init_collection(self):
        """如果集合不存在则创建"""
        if not self._client.collection_exists(COLLECTION_NAME):
            logger.info(f"Qdrant 集合 '{COLLECTION_NAME}' 不存在，正在创建...")
            self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=rest.VectorParams(
                    size=self._vector_size,
                    distance=rest.Distance.COSINE
                )
            )
            
            # 为 Payload 字段建立索引提升查询性能
            indices = ["tenant_id", "project_id", "user_id", "memory_type", "session_id"]
            for field in indices:
                self._client.create_payload_index(
                    collection_name=COLLECTION_NAME,
                    field_name=field,
                    field_schema=rest.PayloadSchemaType.KEYWORD
                )
            logger.info(f"Qdrant 集合 '{COLLECTION_NAME}' 初始化完成")

    def _fragment_to_payload(self, fragment: MemoryFragment) -> dict:
        """MemoryFragment转为极简 Payload 存档，主体数据依靠双写数据库提供"""
        payload = {
            "tenant_id": fragment.tenant_id,
            "project_id": fragment.project_id,
            "user_id": fragment.user_id,
            "memory_type": fragment.memory_type.value,
            "content": fragment.content,
            "created_at": fragment.created_at.isoformat(),
        }
        if fragment.session_id:
            payload["session_id"] = fragment.session_id
        return payload

    def _enrich_with_meta_store(self, items: list[dict], with_score: bool = False) -> list[dict]:
        """将 Qdrant 命中的结果携带全量结构化元数据拼装"""
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
            full_data["content"] = item["content"]
            if with_score and "score" in item:
                full_data["score"] = item["score"]
            enriched.append(full_data)
        
        return enriched

    def _build_filter(self, tenant_id: str, project_id: str, user_id: str, memory_type: Optional[MemoryType] = None, session_id: Optional[str] = None) -> rest.Filter:
        """构建查询所需的 Payload 过滤器"""
        must_conditions = [
            rest.FieldCondition(key="tenant_id", match=rest.MatchValue(value=tenant_id)),
            rest.FieldCondition(key="project_id", match=rest.MatchValue(value=project_id)),
            rest.FieldCondition(key="user_id", match=rest.MatchValue(value=user_id)),
        ]
        
        if memory_type:
            must_conditions.append(rest.FieldCondition(key="memory_type", match=rest.MatchValue(value=memory_type.value)))
        if session_id:
            must_conditions.append(rest.FieldCondition(key="session_id", match=rest.MatchValue(value=session_id)))
            
        return rest.Filter(must=must_conditions)

    # ----------------------------------------------------------
    # 公开 API (对齐原来的 VectorStore)
    # ----------------------------------------------------------

    def add(self, fragment: MemoryFragment) -> None:
        """双写：先写 DB 再写 Vector"""
        self._meta_store.add_memory_fragment(fragment)

        try:
            vector = self._encode(fragment.content)
            payload = self._fragment_to_payload(fragment)
            
            self._client.upsert(
                collection_name=COLLECTION_NAME,
                wait=True,
                points=[
                    rest.PointStruct(
                        id=fragment.id,
                        vector=vector,
                        payload=payload
                    )
                ]
            )
        except Exception as e:
            logger.warning("Qdrant 写入失败，回滚 MetaStore: id=%s", fragment.id, exc_info=True)
            self._meta_store.delete_memory_fragment(fragment.id)
            raise e

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
        """语义搜索记忆"""
        query_vector = self._encode(query)
        query_filter = self._build_filter(tenant_id, project_id, user_id, memory_type, session_id)

        results = self._client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=["content"]
        )

        items = []
        for scored_point in getattr(results, "points", results):
            items.append({
                "id": str(scored_point.id).replace("-", ""),
                "content": scored_point.payload.get("content", ""),
                "score": scored_point.score
            })

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
        """按会话查询关联消息"""
        query_filter = self._build_filter(tenant_id, project_id, user_id, session_id=session_id)
        
        # NOTE: qdrant scroll uses offset as PointId occasionally, but integer offset is supported
        results, next_offset = self._client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=query_filter,
            limit=limit,
            offset=offset if offset else None,
            with_payload=["content", "created_at"]
        )

        items = []
        for record in results:
            items.append({
                "id": str(record.id).replace("-", ""),
                "content": record.payload.get("content", ""),
                "created_at": record.payload.get("created_at", "")
            })

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
        """列出记忆片段"""
        query_filter = self._build_filter(tenant_id, project_id, user_id, memory_type)
        
        results, next_offset = self._client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=query_filter,
            limit=limit,
            offset=offset if offset else None,
            with_payload=["content", "created_at"]
        )

        items = []
        for record in results:
            items.append({
                "id": str(record.id).replace("-", ""),
                "content": record.payload.get("content", ""),
                "created_at": record.payload.get("created_at", "")
            })

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
        """修改记忆片段"""
        old_data = self._meta_store.get_memory_fragment(fragment_id)
        if not old_data:
            return None
        if old_data.get("tenant_id") != tenant_id or old_data.get("project_id") != project_id or old_data.get("user_id") != user_id:
            return None

        # 修改 DB
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

        # 仅修改 Qdrant 中的内容或向量
        if content is not None:
            new_vector = self._encode(content)
            self._client.update_vectors(
                collection_name=COLLECTION_NAME,
                wait=True,
                points=[
                    rest.PointVectors(
                        id=fragment_id,
                        vector=new_vector
                    )
                ]
            )
            self._client.set_payload(
                collection_name=COLLECTION_NAME,
                wait=True,
                payload={"content": content},
                points=[fragment_id]
            )

        logger.debug("更新记忆: id=%s", fragment_id)
        return self._meta_store.get_memory_fragment(fragment_id)

    def delete(self, tenant_id: str, project_id: str, user_id: str, fragment_id: str) -> bool:
        """删除指定记忆片段"""
        old_data = self._meta_store.get_memory_fragment(fragment_id)
        if not old_data:
            return False
        if old_data.get("tenant_id") != tenant_id or old_data.get("project_id") != project_id or old_data.get("user_id") != user_id:
            return False

        success = self._meta_store.delete_memory_fragment(fragment_id)
        if not success:
            return False

        try:
            self._client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=rest.PointIdsList(points=[fragment_id])
            )
            logger.debug("删除记忆: id=%s", fragment_id)
            return True
        except Exception:
            return False

    def get_stats(self, tenant_id: str, project_id: str, user_id: str) -> dict:
        """获取统计数据"""
        return self._meta_store.get_user_stats(tenant_id, project_id, user_id)

    def increment_hit_count(
        self, tenant_id: str, project_id: str, user_id: str, fragment_id: str
    ) -> None:
        """增加记忆片段命中次数"""
        self._meta_store.increment_hit_count(fragment_id)

    def batch_increment_hit_count(
        self, tenant_id: str, project_id: str, fragment_ids: list[str]
    ) -> None:
        """批量增加记忆片段命中次数"""
        self._meta_store.batch_increment_hit_count(fragment_ids)

    def delete_collection(self, tenant_id: str, project_id: str) -> None:
        """兼容老的方法，删除单个租户或项目的分片逻辑，现通过过滤删除 Payload"""
        query_filter = rest.Filter(must=[
            rest.FieldCondition(key="tenant_id", match=rest.MatchValue(value=tenant_id)),
            rest.FieldCondition(key="project_id", match=rest.MatchValue(value=project_id)),
        ])
        try:
            self._client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=rest.FilterSelector(filter=query_filter)
            )
            logger.info(f"已清理 Qdrant 结合对应 project payload 的点: {tenant_id}__{project_id}")
        except Exception as e:
            logger.warning(f"删除 Qdrant points 失败: {tenant_id}__{project_id}, 错误: {e}")
