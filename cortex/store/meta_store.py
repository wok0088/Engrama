"""
SQLite 元数据存储

管理租户（Tenant）、项目（Project）和 API Key 的元信息。
这些信息用于渠道管理和请求认证，不涉及记忆内容本身。
"""

import os
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from cortex import config
from cortex.models import ApiKey, Project, Tenant


class MetaStore:
    """
    SQLite 元数据存储

    管理 Cortex 的组织层级：Tenant → Project → API Key。
    使用 SQLite 作为 V1 的轻量存储方案。
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化 SQLite 数据库连接并创建表

        Args:
            db_path: 数据库文件路径，默认使用配置值
        """
        self._db_path = db_path or str(config.SQLITE_DB_PATH)
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
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
        finally:
            conn.close()

    # ----------------------------------------------------------
    # 租户管理
    # ----------------------------------------------------------

    def create_tenant(self, name: str) -> Tenant:
        """
        注册新租户

        Args:
            name: 租户名称

        Returns:
            创建的 Tenant 对象
        """
        tenant = Tenant(name=name)
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
                (tenant.id, tenant.name, tenant.created_at.isoformat()),
            )
            conn.commit()
        finally:
            conn.close()
        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """获取租户信息"""
        conn = self._get_conn()
        try:
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
        finally:
            conn.close()

    def list_tenants(self) -> list[Tenant]:
        """列出所有租户"""
        conn = self._get_conn()
        try:
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
        finally:
            conn.close()

    # ----------------------------------------------------------
    # 项目管理
    # ----------------------------------------------------------

    def create_project(self, tenant_id: str, name: str) -> Project:
        """
        创建项目

        Args:
            tenant_id: 所属租户 ID
            name: 项目名称

        Returns:
            创建的 Project 对象

        Raises:
            ValueError: 租户不存在
        """
        # 验证租户存在
        if self.get_tenant(tenant_id) is None:
            raise ValueError(f"租户不存在: {tenant_id}")

        project = Project(tenant_id=tenant_id, name=name)
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO projects (id, tenant_id, name, created_at) VALUES (?, ?, ?, ?)",
                (project.id, project.tenant_id, project.name, project.created_at.isoformat()),
            )
            conn.commit()
        finally:
            conn.close()
        return project

    def get_project(self, project_id: str) -> Optional[Project]:
        """获取项目信息"""
        conn = self._get_conn()
        try:
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
        finally:
            conn.close()

    def list_projects(self, tenant_id: str) -> list[Project]:
        """列出租户下的所有项目"""
        conn = self._get_conn()
        try:
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
        finally:
            conn.close()

    def delete_project(self, project_id: str) -> bool:
        """
        删除项目（同时删除关联的 API Key）

        Returns:
            是否成功删除
        """
        conn = self._get_conn()
        try:
            # 先删除关联的 API Key
            conn.execute("DELETE FROM api_keys WHERE project_id = ?", (project_id,))
            cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # ----------------------------------------------------------
    # API Key 管理
    # ----------------------------------------------------------

    def generate_api_key(self, tenant_id: str, project_id: str) -> ApiKey:
        """
        生成 API Key

        Args:
            tenant_id: 租户 ID
            project_id: 项目 ID

        Returns:
            创建的 ApiKey 对象

        Raises:
            ValueError: 租户或项目不存在
        """
        if self.get_tenant(tenant_id) is None:
            raise ValueError(f"租户不存在: {tenant_id}")
        if self.get_project(project_id) is None:
            raise ValueError(f"项目不存在: {project_id}")

        # 生成安全的随机 API Key
        key_value = f"ctx_{secrets.token_urlsafe(32)}"
        api_key = ApiKey(key=key_value, tenant_id=tenant_id, project_id=project_id)

        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO api_keys (key, tenant_id, project_id, created_at, is_active) VALUES (?, ?, ?, ?, ?)",
                (api_key.key, api_key.tenant_id, api_key.project_id, api_key.created_at.isoformat(), 1),
            )
            conn.commit()
        finally:
            conn.close()
        return api_key

    def verify_api_key(self, key: str) -> Optional[ApiKey]:
        """
        验证 API Key

        Args:
            key: API Key 值

        Returns:
            如果 Key 有效返回 ApiKey 对象，否则返回 None
        """
        conn = self._get_conn()
        try:
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
        finally:
            conn.close()

    def revoke_api_key(self, key: str) -> bool:
        """
        吊销 API Key

        Returns:
            是否成功吊销
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "UPDATE api_keys SET is_active = 0 WHERE key = ?", (key,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
