"""
渠道管理器

管理租户注册、项目创建/删除、API Key 生成/验证等渠道管理功能。
这是 MetaStore 的业务层封装。
"""

from typing import Optional

from cortex.models import ApiKey, Project, Tenant
from cortex.store.meta_store import MetaStore


class ChannelManager:
    """
    渠道管理器

    使用示例：
    ```python
    from cortex.channel_manager import ChannelManager

    cm = ChannelManager()

    # 注册租户
    tenant = cm.register_tenant("携程旅行")

    # 创建项目
    project = cm.create_project(tenant.id, "酒店 AI 助手")

    # 生成 API Key
    api_key = cm.generate_api_key(tenant.id, project.id)
    print(f"API Key: {api_key.key}")

    # 验证 API Key
    verified = cm.verify_api_key(api_key.key)
    ```
    """

    def __init__(self, meta_store: Optional[MetaStore] = None):
        """
        初始化渠道管理器

        Args:
            meta_store: 元数据存储实例，默认自动创建
        """
        self._meta_store = meta_store or MetaStore()

    # ----------------------------------------------------------
    # 租户管理
    # ----------------------------------------------------------

    def register_tenant(self, name: str) -> Tenant:
        """
        注册新租户

        Args:
            name: 租户名称

        Returns:
            创建的 Tenant 对象
        """
        return self._meta_store.create_tenant(name)

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """获取租户信息"""
        return self._meta_store.get_tenant(tenant_id)

    def list_tenants(self) -> list[Tenant]:
        """列出所有租户"""
        return self._meta_store.list_tenants()

    # ----------------------------------------------------------
    # 项目管理
    # ----------------------------------------------------------

    def create_project(self, tenant_id: str, name: str) -> Project:
        """
        创建项目

        Args:
            tenant_id: 租户 ID
            name: 项目名称

        Returns:
            创建的 Project 对象

        Raises:
            ValueError: 租户不存在
        """
        return self._meta_store.create_project(tenant_id, name)

    def get_project(self, project_id: str) -> Optional[Project]:
        """获取项目信息"""
        return self._meta_store.get_project(project_id)

    def list_projects(self, tenant_id: str) -> list[Project]:
        """列出租户下的所有项目"""
        return self._meta_store.list_projects(tenant_id)

    def delete_project(self, project_id: str) -> bool:
        """删除项目"""
        return self._meta_store.delete_project(project_id)

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
        return self._meta_store.generate_api_key(tenant_id, project_id)

    def verify_api_key(self, key: str) -> Optional[ApiKey]:
        """
        验证 API Key

        Args:
            key: API Key 值

        Returns:
            如果有效返回 ApiKey 对象，否则返回 None
        """
        return self._meta_store.verify_api_key(key)

    def revoke_api_key(self, key: str) -> bool:
        """吊销 API Key"""
        return self._meta_store.revoke_api_key(key)
