"""
基础元数据存储接口

定义租户、项目和 API Key 的抽象存储规范。
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

from engrama.models import ApiKey, Project, Tenant, MemoryFragment


class BaseMetaStore(ABC):
    """元数据存储基础接口"""

    @abstractmethod
    def create_tenant(self, name: str) -> Tenant:
        pass

    @abstractmethod
    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        pass

    @abstractmethod
    def list_tenants(self) -> list[Tenant]:
        pass

    @abstractmethod
    def delete_tenant(self, tenant_id: str) -> bool:
        pass

    @abstractmethod
    def create_project(self, tenant_id: str, name: str) -> Project:
        pass

    @abstractmethod
    def get_project(self, project_id: str) -> Optional[Project]:
        pass

    @abstractmethod
    def list_projects(self, tenant_id: str) -> list[Project]:
        pass

    @abstractmethod
    def delete_project(self, project_id: str, tenant_id: str) -> bool:
        pass

    @abstractmethod
    def generate_api_key(self, tenant_id: str, project_id: str, user_id: str = None) -> ApiKey:
        pass

    @abstractmethod
    def verify_api_key(self, key: str) -> Optional[ApiKey]:
        pass

    @abstractmethod
    def revoke_api_key(self, key_id: str) -> bool:
        pass

    @abstractmethod
    def list_api_keys(self, project_id: str) -> list[dict]:
        pass

    # ----------------------------------------------------------
    # 记忆元数据与统计信息管理 (双写同步)
    # ----------------------------------------------------------

    @abstractmethod
    def add_memory_fragment(self, fragment: MemoryFragment) -> None:
        """保存记忆片段的元数据"""
        pass

    @abstractmethod
    def get_memory_fragment(self, fragment_id: str) -> Optional[dict]:
        """获取单个记忆片段的所有元数据"""
        pass

    @abstractmethod
    def get_memory_fragments(self, fragment_ids: List[str]) -> List[dict]:
        """批量获取记忆片段的元数据"""
        pass

    @abstractmethod
    def update_memory_fragment(self, fragment_id: str, updates: Dict[str, Any]) -> bool:
        """更新记忆片段的元数据"""
        pass

    @abstractmethod
    def delete_memory_fragment(self, fragment_id: str) -> bool:
        """删除记忆片段的元数据"""
        pass

    @abstractmethod
    def increment_hit_count(self, fragment_id: str) -> None:
        """增加命中次数"""
        pass

    @abstractmethod
    def batch_increment_hit_count(self, fragment_ids: List[str]) -> None:
        """批量增加命中次数"""
        pass

    @abstractmethod
    def get_user_stats(self, tenant_id: str, project_id: str, user_id: str) -> dict:
        """获取用户的记忆统计信息"""
        pass
