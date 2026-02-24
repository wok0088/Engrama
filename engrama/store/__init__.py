"""
存储层

- VectorStore: ChromaDB 向量存储（语义搜索）
- BaseMetaStore: 元数据存储抽象
- SQLiteMetaStore: SQLite 元数据存储实现
- PostgresMetaStore: PostgreSQL 元数据存储实现
"""

from engrama.store.base_meta_store import BaseMetaStore
from engrama.store.sqlite_store import SQLiteMetaStore
from engrama.store.postgres_store import PostgresMetaStore
from engrama import config

def create_meta_store() -> BaseMetaStore:
    """创建并返回配置的 MetaStore 实例"""
    if config.DB_TYPE == "postgres":
        return PostgresMetaStore()
    else:
        return SQLiteMetaStore()
