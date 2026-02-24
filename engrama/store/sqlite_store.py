"""
SQLite 元数据存储

管理租户（Tenant）、项目（Project）和 API Key 的元信息。
不使用 threading.local()，而是每次获取新连接以支持协程环境下的高并发。
"""

import hashlib
import os
import secrets
import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, Generator, List, Dict, Any

from engrama import config
from engrama.logger import get_logger
from engrama.models import ApiKey, Project, Tenant, MemoryFragment
from engrama.store.base_meta_store import BaseMetaStore

logger = get_logger(__name__)


def _hash_key(key: str) -> str:
    """计算 API Key 的 SHA-256 哈希值"""
    return hashlib.sha256(key.encode()).hexdigest()


def _extract_key_id(key: str) -> str:
    """从完整 Key 中提取短标识（前 12 字符，如 'eng_Ab3xYz8w'）"""
    return key[:12]


class SQLiteMetaStore(BaseMetaStore):
    """
    SQLite 元数据存储
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化 SQLite 数据库连接并创建表
        """
        self._db_path = db_path or str(config.SQLITE_DB_PATH)
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_tables()

    @contextmanager
    def _get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        """获取短生命周期的数据库连接"""
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            yield conn
        finally:
            conn.close()

    def _init_tables(self) -> None:
        """创建数据库表"""
        with self._get_conn() as conn:
            try:
                # Disable foreign keys during table creation/migration to avoid issues
                conn.execute("PRAGMA foreign_keys=OFF")

                # Check if api_keys exists and needs migration before running executescript
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='api_keys'")
                api_keys_exists = cursor.fetchone() is not None

                needs_migration = False
                if api_keys_exists:
                    cursor = conn.execute("PRAGMA table_info(api_keys)")
                    columns = [row["name"] for row in cursor.fetchall()]
                    if "key_hash" not in columns:
                        needs_migration = True
                        logger.info("Migrating api_keys table to include key_hash column...")
                        # 1. Add key_hash column
                        conn.execute("ALTER TABLE api_keys ADD COLUMN key_hash TEXT")

                        # 2. Add full_key column if it exists in the old schema
                        if "full_key" in columns:
                            conn.execute("UPDATE api_keys SET key_hash = full_key")
                        else:
                            # Fallback for empty table or edge cases
                            # Note: key_id doesn't exist either in sqlite table PRAGMA table_info sometimes?
                            # Wait, the error is `no such column: key_id` during UPDATE?
                            # Let's check if the column is actually named `key_id` or `id`?
                            if "id" in columns:
                                conn.execute("UPDATE api_keys SET key_hash = id || '_hash'")
                            elif "key_id" in columns:
                                conn.execute("UPDATE api_keys SET key_hash = key_id || '_hash'")
                            else:
                                conn.execute("UPDATE api_keys SET key_hash = 'unknown_hash_' || hex(randomblob(4))")

                conn.executescript("""
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

                # Re-enable foreign keys
                conn.execute("PRAGMA foreign_keys=ON")

                conn.commit()
                logger.info("数据库表初始化完成: %s", self._db_path)
            except Exception as e:
                logger.error("数据库初始化失败: %s", e)
                raise

    def create_tenant(self, name: str) -> Tenant:
        tenant = Tenant(name=name)
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
                (tenant.id, tenant.name, tenant.created_at.isoformat()),
            )
            conn.commit()
        logger.info("注册租户: id=%s, name=%s", tenant.id, tenant.name)
        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id, name, created_at FROM tenants WHERE id = ?",
                (tenant_id,),
            ).fetchone()
            if row is None:
                return None
            return Tenant(
                id=row["id"],
                name=row["name"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )

    def list_tenants(self) -> list[Tenant]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, name, created_at FROM tenants ORDER BY created_at DESC"
            ).fetchall()
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

        with self._get_conn() as conn:
            keys_to_delete = conn.execute(
                "SELECT key_id FROM api_keys WHERE tenant_id = ?", (tenant_id,)
            ).fetchall()
            for row in keys_to_delete:
                logger.info("级联删除 API Key: key_id=%s (租户删除)", row["key_id"])

            conn.execute("DELETE FROM api_keys WHERE tenant_id = ?", (tenant_id,))
            conn.execute("DELETE FROM projects WHERE tenant_id = ?", (tenant_id,))
            cursor = conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
            conn.commit()

            deleted = cursor.rowcount > 0
            if deleted:
                logger.info("删除租户: id=%s", tenant_id)
            return deleted

    def create_project(self, tenant_id: str, name: str) -> Project:
        if self.get_tenant(tenant_id) is None:
            raise ValueError(f"租户不存在: {tenant_id}")

        project = Project(tenant_id=tenant_id, name=name)
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO projects (id, tenant_id, name, created_at) VALUES (?, ?, ?, ?)",
                (project.id, project.tenant_id, project.name, project.created_at.isoformat()),
            )
            conn.commit()
        logger.info("创建项目: id=%s, tenant=%s, name=%s", project.id, tenant_id, project.name)
        return project

    def get_project(self, project_id: str) -> Optional[Project]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id, tenant_id, name, created_at FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if row is None:
                return None
            return Project(
                id=row["id"],
                tenant_id=row["tenant_id"],
                name=row["name"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )

    def list_projects(self, tenant_id: str) -> list[Project]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, tenant_id, name, created_at FROM projects WHERE tenant_id = ? ORDER BY created_at DESC",
                (tenant_id,),
            ).fetchall()
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

        with self._get_conn() as conn:
            conn.execute("DELETE FROM api_keys WHERE project_id = ?", (project_id,))
            cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
            deleted = cursor.rowcount > 0
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

        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO api_keys (key_id, key_hash, tenant_id, project_id, user_id, created_at, is_active) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (api_key.key_id, api_key.key_hash, api_key.tenant_id, api_key.project_id, api_key.user_id, api_key.created_at.isoformat(), 1),
            )
            conn.commit()
        return api_key

    def verify_api_key(self, key: str) -> Optional[ApiKey]:
        key_hash = _hash_key(key)
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT key_id, key_hash, tenant_id, project_id, user_id, created_at, is_active FROM api_keys WHERE key_hash = ? AND is_active = 1",
                (key_hash,),
            ).fetchone()
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
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE api_keys SET is_active = 0 WHERE key_id = ? AND is_active = 1", (key_id,)
            )
            conn.commit()
            revoked = cursor.rowcount > 0
            if revoked:
                logger.info("吊销 API Key: key_id=%s", key_id)
            return revoked

    def list_api_keys(self, project_id: str) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT key_id, tenant_id, project_id, user_id, created_at, is_active FROM api_keys WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
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
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO memory_fragments
                (id, tenant_id, project_id, user_id, memory_type, content, role, session_id, tags, importance, hit_count, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    fragment.created_at,
                    fragment.updated_at,
                ),
            )
            conn.commit()

    def get_memory_fragment(self, fragment_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM memory_fragments WHERE id = ?",
                (fragment_id,),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            if result.get("tags") is not None:
                result["tags"] = json.loads(result["tags"])
            else:
                result["tags"] = []
                
            if result.get("metadata") is not None:
                result["metadata"] = json.loads(result["metadata"])
            else:
                result["metadata"] = None
            return result

    def get_memory_fragments(self, fragment_ids: List[str]) -> List[dict]:
        if not fragment_ids:
            return []
        placeholders = ",".join("?" * len(fragment_ids))
        with self._get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM memory_fragments WHERE id IN ({placeholders})",
                fragment_ids,
            ).fetchall()
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

        set_clauses = []
        values = []
        for k, v in updates.items():
            set_clauses.append(f"{k} = ?")
            if k in ("tags", "metadata") and v is not None:
                values.append(json.dumps(v))
            else:
                values.append(v)

        set_clauses.append("updated_at = ?")
        values.append(datetime.utcnow().isoformat() + "Z")
        values.append(fragment_id)

        query = f"UPDATE memory_fragments SET {', '.join(set_clauses)} WHERE id = ?"
        with self._get_conn() as conn:
            cursor = conn.execute(query, values)
            conn.commit()
            return cursor.rowcount > 0

    def delete_memory_fragment(self, fragment_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM memory_fragments WHERE id = ?", (fragment_id,))
            conn.commit()
            return cursor.rowcount > 0

    def increment_hit_count(self, fragment_id: str) -> None:
        with self._get_conn() as conn:
            conn.execute("UPDATE memory_fragments SET hit_count = hit_count + 1 WHERE id = ?", (fragment_id,))
            conn.commit()

    def batch_increment_hit_count(self, fragment_ids: List[str]) -> None:
        if not fragment_ids:
            return
        placeholders = ",".join("?" * len(fragment_ids))
        with self._get_conn() as conn:
            conn.execute(f"UPDATE memory_fragments SET hit_count = hit_count + 1 WHERE id IN ({placeholders})", fragment_ids)
            conn.commit()

    def get_user_stats(self, tenant_id: str, project_id: str, user_id: str) -> dict:
        with self._get_conn() as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) as total FROM memory_fragments WHERE tenant_id = ? AND project_id = ? AND user_id = ?",
                (tenant_id, project_id, user_id)
            ).fetchone()

            type_rows = conn.execute(
                "SELECT memory_type, COUNT(*) as count FROM memory_fragments WHERE tenant_id = ? AND project_id = ? AND user_id = ? GROUP BY memory_type",
                (tenant_id, project_id, user_id)
            ).fetchall()

            stats = {
                "total": total_row["total"] if total_row else 0,
                "by_type": {}
            }
            for row in type_rows:
                stats["by_type"][row["memory_type"]] = row["count"]
            return stats
