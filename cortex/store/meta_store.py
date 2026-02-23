"""
SQLite 元数据存储

管理租户（Tenant）、项目（Project）和 API Key 的元信息。
使用线程级连接管理，确保并发安全。
"""

import os
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from cortex import config
from cortex.logger import get_logger
from cortex.models import ApiKey, Project, Tenant

logger = get_logger(__name__)


class MetaStore:
    """
    SQLite 元数据存储

    管理 Engrama 的组织层级：Tenant → Project → API Key。
    使用线程级连接池确保并发安全。
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化 SQLite 数据库连接并创建表

        Args:
            db_path: 数据库文件路径，默认使用配置值
        """
        self._db_path = db_path or str(config.SQLITE_DB_PATH)
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._local = threading.local()
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接（线程安全）"""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    def _init_tables(self) -> None:
        """创建数据库表"""
        conn = self._get_conn()
        try:
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
                    key TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                );

                CREATE INDEX IF NOT EXISTS idx_projects_tenant ON projects(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_api_keys_project ON api_keys(project_id);
            """)
            conn.commit()
            logger.info("数据库表初始化完成: %s", self._db_path)
        except Exception as e:
            logger.error("数据库初始化失败: %s", e)
            raise

    # ----------------------------------------------------------
    # 租户管理
    # ----------------------------------------------------------

    def create_tenant(self, name: str) -> Tenant:
        """注册新租户"""
        tenant = Tenant(name=name)
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
            (tenant.id, tenant.name, tenant.created_at.isoformat()),
        )
        conn.commit()
        logger.info("注册租户: id=%s, name=%s", tenant.id, tenant.name)
        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """获取租户信息"""
        conn = self._get_conn()
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
        """列出所有租户"""
        conn = self._get_conn()
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

    # ----------------------------------------------------------
    # 项目管理
    # ----------------------------------------------------------

    def create_project(self, tenant_id: str, name: str) -> Project:
        """创建项目"""
        if self.get_tenant(tenant_id) is None:
            raise ValueError(f"租户不存在: {tenant_id}")

        project = Project(tenant_id=tenant_id, name=name)
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO projects (id, tenant_id, name, created_at) VALUES (?, ?, ?, ?)",
            (project.id, project.tenant_id, project.name, project.created_at.isoformat()),
        )
        conn.commit()
        logger.info("创建项目: id=%s, tenant=%s, name=%s", project.id, tenant_id, project.name)
        return project

    def get_project(self, project_id: str) -> Optional[Project]:
        """获取项目信息"""
        conn = self._get_conn()
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
        """列出租户下的所有项目"""
        conn = self._get_conn()
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

    def delete_project(self, project_id: str) -> bool:
        """删除项目（同时删除关联的 API Key）"""
        conn = self._get_conn()
        conn.execute("DELETE FROM api_keys WHERE project_id = ?", (project_id,))
        cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("删除项目: id=%s", project_id)
        return deleted

    # ----------------------------------------------------------
    # API Key 管理
    # ----------------------------------------------------------

    def generate_api_key(self, tenant_id: str, project_id: str) -> ApiKey:
        """生成 API Key"""
        if self.get_tenant(tenant_id) is None:
            raise ValueError(f"租户不存在: {tenant_id}")
        if self.get_project(project_id) is None:
            raise ValueError(f"项目不存在: {project_id}")

        key_value = f"ctx_{secrets.token_urlsafe(32)}"
        api_key = ApiKey(key=key_value, tenant_id=tenant_id, project_id=project_id)

        conn = self._get_conn()
        conn.execute(
            "INSERT INTO api_keys (key, tenant_id, project_id, created_at, is_active) VALUES (?, ?, ?, ?, ?)",
            (api_key.key, api_key.tenant_id, api_key.project_id, api_key.created_at.isoformat(), 1),
        )
        conn.commit()
        logger.info("生成 API Key: tenant=%s, project=%s", tenant_id, project_id)
        return api_key

    def verify_api_key(self, key: str) -> Optional[ApiKey]:
        """验证 API Key"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT key, tenant_id, project_id, created_at, is_active FROM api_keys WHERE key = ? AND is_active = 1",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return ApiKey(
            key=row["key"],
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            is_active=bool(row["is_active"]),
        )

    def revoke_api_key(self, key: str) -> bool:
        """吊销 API Key"""
        conn = self._get_conn()
        cursor = conn.execute(
            "UPDATE api_keys SET is_active = 0 WHERE key = ?", (key,)
        )
        conn.commit()
        revoked = cursor.rowcount > 0
        if revoked:
            logger.info("吊销 API Key")
        return revoked
