"""
PostgreSQL 元数据存储

使用 psycopg 连接池管理租户（Tenant）、项目（Project）和 API Key 的元信息。
"""

import hashlib
import os
import secrets
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional, Generator, List, Dict, Any

from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

from engrama import config
from engrama.logger import get_logger
from engrama.models import ApiKey, Project, Tenant, MemoryFragment
from engrama.store.base_meta_store import BaseMetaStore

logger = get_logger(__name__)

# 允许通过 update_memory_fragment 更新的列白名单（防止 SQL 注入）
_UPDATABLE_COLUMNS = {"content", "tags", "importance", "metadata"}


def _hash_key(key: str) -> str:
    """计算 API Key 的 SHA-256 哈希值"""
    return hashlib.sha256(key.encode()).hexdigest()


def _extract_key_id(key: str) -> str:
    """从完整 Key 中提取短标识（前 12 字符，如 'eng_Ab3xYz8w'）"""
    return key[:12]


class PostgresMetaStore(BaseMetaStore):
    """
    PostgreSQL 元数据存储
    """

    def __init__(self, pg_uri: Optional[str] = None):
        """
        初始化 PostgreSQL 数据库连接池并创建表
        """
        self._pg_uri = pg_uri or config.PG_URI
        if not self._pg_uri:
            raise ValueError("ENGRAMA_PG_URI must be provided for PostgresMetaStore")

        # Configure the connection pool
        self._pool = ConnectionPool(
            conninfo=self._pg_uri,
            min_size=2,
            max_size=20,
            kwargs={"row_factory": dict_row}
        )
        self._init_tables()

    def _init_tables(self) -> None:
        """创建数据库表"""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS tenants (
                            id TEXT PRIMARY KEY,
                            name TEXT NOT NULL,
                            created_at TEXT NOT NULL
                        );

                        CREATE TABLE IF NOT EXISTS projects (
                            id TEXT PRIMARY KEY,
                            tenant_id TEXT NOT NULL,
                            name TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            FOREIGN KEY (tenant_id) REFERENCES tenants(id)
                        );

                        CREATE TABLE IF NOT EXISTS api_keys (
                            key_id TEXT PRIMARY KEY,
                            key_hash TEXT NOT NULL UNIQUE,
                            tenant_id TEXT NOT NULL,
                            project_id TEXT NOT NULL,
                            user_id TEXT DEFAULT NULL,
                            created_at TEXT NOT NULL,
                            is_active INTEGER NOT NULL DEFAULT 1,
                            FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                            FOREIGN KEY (project_id) REFERENCES projects(id)
                        );

                        CREATE INDEX IF NOT EXISTS idx_projects_tenant ON projects(tenant_id);
                        CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys(tenant_id);
                        CREATE INDEX IF NOT EXISTS idx_api_keys_project ON api_keys(project_id);
                        CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);

                        CREATE TABLE IF NOT EXISTS memory_fragments (
                            id TEXT PRIMARY KEY,
                            tenant_id TEXT NOT NULL,
                            project_id TEXT NOT NULL,
                            user_id TEXT NOT NULL,
                            memory_type TEXT NOT NULL,
                            content TEXT NOT NULL,
                            role TEXT,
                            session_id TEXT,
                            tags TEXT,
                            importance REAL NOT NULL DEFAULT 0.0,
                            hit_count INTEGER NOT NULL DEFAULT 0,
                            metadata TEXT,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        );

                        CREATE INDEX IF NOT EXISTS idx_memory_fragments_user ON memory_fragments(tenant_id, project_id, user_id);
                        CREATE INDEX IF NOT EXISTS idx_memory_fragments_session ON memory_fragments(session_id);
                    """)

                    # Handle key_hash migration for existing tables
                    cur.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name='api_keys' AND column_name='key_hash'
                    """)
                    if cur.fetchone() is None:
                        logger.info("Migrating api_keys table to include key_hash column...")
                        # 1. Add key_hash column
                        cur.execute("ALTER TABLE api_keys ADD COLUMN key_hash TEXT")

                        # 2. Add full_key column if it exists in the old schema
                        cur.execute("""
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_name='api_keys' AND column_name='full_key'
                        """)
                        if cur.fetchone() is not None:
                            cur.execute("UPDATE api_keys SET key_hash = full_key")
                        else:
                            cur.execute("UPDATE api_keys SET key_hash = key_id || '_hash'")

                        # Set to NOT NULL and add UNIQUE constraint
                        cur.execute("ALTER TABLE api_keys ALTER COLUMN key_hash SET NOT NULL")
                        cur.execute("ALTER TABLE api_keys ADD CONSTRAINT api_keys_key_hash_key UNIQUE (key_hash)")

                        # Create the index
                        cur.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)")
                    conn.commit()
                    logger.info("PostgreSQL 数据库表初始化完成")
                except Exception as e:
                    logger.error("PostgreSQL 数据库初始化失败: %s", e)
                    raise

    def create_tenant(self, name: str) -> Tenant:
        tenant = Tenant(name=name)
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO tenants (id, name, created_at) VALUES (%s, %s, %s)",
                    (tenant.id, tenant.name, tenant.created_at.isoformat()),
                )
                conn.commit()
        logger.info("注册租户: id=%s, name=%s", tenant.id, tenant.name)
        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, created_at FROM tenants WHERE id = %s",
                    (tenant_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return Tenant(
                    id=row["id"],
                    name=row["name"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )

    def list_tenants(self) -> list[Tenant]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, created_at FROM tenants ORDER BY created_at DESC"
                )
                rows = cur.fetchall()
                return [
                    Tenant(
                        id=row["id"],
                        name=row["name"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                    )
                    for row in rows
                ]

    def delete_tenant(self, tenant_id: str) -> bool:
        if self.get_tenant(tenant_id) is None:
            return False

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT key_id FROM api_keys WHERE tenant_id = %s", (tenant_id,)
                )
                keys_to_delete = cur.fetchall()
                for row in keys_to_delete:
                    logger.info("级联删除 API Key: key_id=%s (租户删除)", row["key_id"])

                cur.execute("DELETE FROM api_keys WHERE tenant_id = %s", (tenant_id,))
                cur.execute("DELETE FROM projects WHERE tenant_id = %s", (tenant_id,))
                cur.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))

                deleted = cur.rowcount > 0
                conn.commit()

                if deleted:
                    logger.info("删除租户: id=%s", tenant_id)
                return deleted

    def create_project(self, tenant_id: str, name: str) -> Project:
        if self.get_tenant(tenant_id) is None:
            raise ValueError(f"租户不存在: {tenant_id}")

        project = Project(tenant_id=tenant_id, name=name)
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO projects (id, tenant_id, name, created_at) VALUES (%s, %s, %s, %s)",
                    (project.id, project.tenant_id, project.name, project.created_at.isoformat()),
                )
                conn.commit()
        logger.info("创建项目: id=%s, tenant=%s, name=%s", project.id, tenant_id, project.name)
        return project

    def get_project(self, project_id: str) -> Optional[Project]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, tenant_id, name, created_at FROM projects WHERE id = %s",
                    (project_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return Project(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    name=row["name"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )

    def list_projects(self, tenant_id: str) -> list[Project]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, tenant_id, name, created_at FROM projects WHERE tenant_id = %s ORDER BY created_at DESC",
                    (tenant_id,),
                )
                rows = cur.fetchall()
                return [
                    Project(
                        id=row["id"],
                        tenant_id=row["tenant_id"],
                        name=row["name"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                    )
                    for row in rows
                ]

    def delete_project(self, project_id: str, tenant_id: str) -> bool:
        project = self.get_project(project_id)
        if project is None or project.tenant_id != tenant_id:
            return False

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM api_keys WHERE project_id = %s", (project_id,))
                cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))

                deleted = cur.rowcount > 0
                conn.commit()
                if deleted:
                    logger.info("删除项目: id=%s, tenant=%s", project_id, tenant_id)
                return deleted

    def generate_api_key(self, tenant_id: str, project_id: str, user_id: str = None) -> ApiKey:
        if self.get_tenant(tenant_id) is None:
            raise ValueError(f"租户不存在: {tenant_id}")

        project = self.get_project(project_id)
        if project is None or project.tenant_id != tenant_id:
            raise ValueError(f"项目不存在或不属于该租户: {project_id}")

        key_value = f"eng_{secrets.token_urlsafe(32)}"
        key_id = _extract_key_id(key_value)
        key_hash = _hash_key(key_value)

        api_key = ApiKey(
            key=key_value,
            key_id=key_id,
            key_hash=key_hash,
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
        )

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO api_keys (key_id, key_hash, tenant_id, project_id, user_id, created_at, is_active) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (api_key.key_id, api_key.key_hash, api_key.tenant_id, api_key.project_id, api_key.user_id, api_key.created_at.isoformat(), 1),
                )
                conn.commit()
        return api_key

    def verify_api_key(self, key: str) -> Optional[ApiKey]:
        key_hash = _hash_key(key)
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT key_id, key_hash, tenant_id, project_id, user_id, created_at, is_active FROM api_keys WHERE key_hash = %s AND is_active = 1",
                    (key_hash,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return ApiKey(
                    key=key,
                    key_id=row["key_id"],
                    key_hash=row["key_hash"],
                    tenant_id=row["tenant_id"],
                    project_id=row["project_id"],
                    user_id=row["user_id"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    is_active=bool(row["is_active"]),
                )

    def revoke_api_key(self, key_id: str) -> bool:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE api_keys SET is_active = 0 WHERE key_id = %s AND is_active = 1", (key_id,)
                )
                revoked = cur.rowcount > 0
                conn.commit()
                if revoked:
                    logger.info("吊销 API Key: key_id=%s", key_id)
                return revoked

    def list_api_keys(self, project_id: str) -> list[dict]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT key_id, tenant_id, project_id, user_id, created_at, is_active FROM api_keys WHERE project_id = %s ORDER BY created_at DESC",
                    (project_id,),
                )
                rows = cur.fetchall()
                return [
                    {
                        "key_id": row["key_id"],
                        "tenant_id": row["tenant_id"],
                        "project_id": row["project_id"],
                        "user_id": row["user_id"],
                        "created_at": row["created_at"],
                        "is_active": bool(row["is_active"]),
                    }
                    for row in rows
                ]

    # ----------------------------------------------------------
    # 记忆元数据与统计信息管理 (双写同步)
    # ----------------------------------------------------------

    def add_memory_fragment(self, fragment: MemoryFragment) -> None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO memory_fragments
                    (id, tenant_id, project_id, user_id, memory_type, content, role, session_id, tags, importance, hit_count, metadata, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        fragment.id,
                        fragment.tenant_id,
                        fragment.project_id,
                        fragment.user_id,
                        fragment.memory_type.value,
                        fragment.content,
                        fragment.role.value if fragment.role else None,
                        fragment.session_id,
                        json.dumps(fragment.tags) if fragment.tags else None,
                        fragment.importance,
                        fragment.hit_count,
                        json.dumps(fragment.metadata) if fragment.metadata else None,
                        fragment.created_at.isoformat(),
                        fragment.updated_at.isoformat(),
                    ),
                )
                conn.commit()

    def get_memory_fragment(self, fragment_id: str) -> Optional[dict]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM memory_fragments WHERE id = %s",
                    (fragment_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                result = dict(row)
                if result.get("tags"):
                    result["tags"] = json.loads(result["tags"])
                else:
                    result["tags"] = []
                if result.get("metadata"):
                    result["metadata"] = json.loads(result["metadata"])
                return result

    def get_memory_fragments(self, fragment_ids: List[str]) -> List[dict]:
        if not fragment_ids:
            return []
        placeholders = ",".join(["%s"] * len(fragment_ids))
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM memory_fragments WHERE id IN ({placeholders})",
                    fragment_ids,
                )
                rows = cur.fetchall()
                results = []
                for row in rows:
                    result = dict(row)
                    if result.get("tags"):
                        result["tags"] = json.loads(result["tags"])
                    else:
                        result["tags"] = []
                    if result.get("metadata"):
                        result["metadata"] = json.loads(result["metadata"])
                    results.append(result)
                return results

    def update_memory_fragment(self, fragment_id: str, updates: Dict[str, Any]) -> bool:
        if not updates:
            return True

        # 白名单校验：防止通过构造恶意 key 进行 SQL 注入
        invalid_cols = set(updates.keys()) - _UPDATABLE_COLUMNS
        if invalid_cols:
            raise ValueError(f"不允许更新字段: {invalid_cols}")

        set_clauses = []
        values = []
        for k, v in updates.items():
            set_clauses.append(f"{k} = %s")
            if k in ("tags", "metadata") and v is not None:
                values.append(json.dumps(v))
            else:
                values.append(v)

        set_clauses.append("updated_at = %s")
        values.append(datetime.now(timezone.utc).isoformat())
        values.append(fragment_id)

        query = f"UPDATE memory_fragments SET {', '.join(set_clauses)} WHERE id = %s"
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
                conn.commit()
                return cur.rowcount > 0

    def delete_memory_fragment(self, fragment_id: str) -> bool:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM memory_fragments WHERE id = %s", (fragment_id,))
                conn.commit()
                return cur.rowcount > 0

    def increment_hit_count(self, fragment_id: str) -> None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE memory_fragments SET hit_count = hit_count + 1 WHERE id = %s", (fragment_id,))
                conn.commit()

    def batch_increment_hit_count(self, fragment_ids: List[str]) -> None:
        if not fragment_ids:
            return
        placeholders = ",".join(["%s"] * len(fragment_ids))
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"UPDATE memory_fragments SET hit_count = hit_count + 1 WHERE id IN ({placeholders})", fragment_ids)
                conn.commit()

    def get_user_stats(self, tenant_id: str, project_id: str, user_id: str) -> dict:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) as total FROM memory_fragments WHERE tenant_id = %s AND project_id = %s AND user_id = %s",
                    (tenant_id, project_id, user_id)
                )
                total_row = cur.fetchone()

                cur.execute(
                    "SELECT memory_type, COUNT(*) as count FROM memory_fragments WHERE tenant_id = %s AND project_id = %s AND user_id = %s GROUP BY memory_type",
                    (tenant_id, project_id, user_id)
                )
                type_rows = cur.fetchall()

                stats = {
                    "total": total_row["total"] if total_row else 0,
                    "by_type": {}
                }
                for row in type_rows:
                    stats["by_type"][row["memory_type"]] = row["count"]
                return stats

    def close(self):
        """Close the connection pool"""
        if self._pool:
            self._pool.close()
