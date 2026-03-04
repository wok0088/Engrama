"""
渠道管理器测试

测试 ChannelManager 的租户/项目/API Key 管理功能。
"""

import os

import pytest

from engrama.store.base_meta_store import BaseMetaStore
from engrama.store import create_meta_store
from engrama.channel_manager import ChannelManager


@pytest.fixture(scope="module")
def cm():
    """创建 ChannelManager 实例"""
    ms = create_meta_store()
    return ChannelManager(meta_store=ms)


class TestChannelManager:
    """ChannelManager 测试用例"""

    def test_register_tenant(self, cm):
        """注册租户"""
        tenant = cm.register_tenant("携程旅行")
        assert tenant.name == "携程旅行"
        assert tenant.id is not None

    def test_register_duplicate_tenant(self, cm):
        """注册同名租户应抛出 ValueError"""
        cm.register_tenant("重复租户")
        with pytest.raises(ValueError, match="同名租户已存在"):
            cm.register_tenant("重复租户")

    def test_get_tenant(self, cm):
        """获取租户"""
        tenant = cm.register_tenant("测试")
        fetched = cm.get_tenant(tenant.id)
        assert fetched is not None
        assert fetched.name == "测试"

    def test_list_tenants(self, cm):
        """列出租户"""
        cm.register_tenant("A")
        cm.register_tenant("B")
        assert len(cm.list_tenants()) == 2

    def test_create_project(self, cm):
        """创建项目"""
        tenant = cm.register_tenant("测试创建")
        project = cm.create_project(tenant.id, "酒店 AI")
        assert project.name == "酒店 AI"
        assert project.tenant_id == tenant.id

    def test_create_duplicate_project(self, cm):
        """同一租户下创建同名项目应抛出 ValueError"""
        tenant = cm.register_tenant("独占租户")
        cm.create_project(tenant.id, "重复项目")
        with pytest.raises(ValueError, match="该租户下同名项目已存在"):
            cm.create_project(tenant.id, "重复项目")

    def test_create_project_invalid_tenant(self, cm):
        """无效租户创建项目失败"""
        with pytest.raises(ValueError):
            cm.create_project("nonexistent", "项目")

    def test_list_projects(self, cm):
        """列出项目"""
        tenant = cm.register_tenant("测试")
        cm.create_project(tenant.id, "项目 A")
        cm.create_project(tenant.id, "项目 B")
        projects = cm.list_projects(tenant.id)
        assert len(projects) == 2

    def test_delete_project(self, cm):
        """删除项目（需传 tenant_id）"""
        tenant = cm.register_tenant("测试")
        project = cm.create_project(tenant.id, "待删除")
        assert cm.delete_project(project.id, tenant_id=tenant.id)
        assert cm.get_project(project.id) is None

    def test_delete_project_wrong_tenant(self, cm):
        """用错误 tenant_id 删除项目应失败"""
        tenant = cm.register_tenant("测试")
        project = cm.create_project(tenant.id, "项目")
        assert not cm.delete_project(project.id, tenant_id="wrong_tenant")
        assert cm.get_project(project.id) is not None

    def test_api_key_flow(self, cm):
        """完整的 API Key 流程：生成 → 验证 → 吊销"""
        tenant = cm.register_tenant("测试")
        project = cm.create_project(tenant.id, "项目")

        # 生成
        api_key = cm.generate_api_key(tenant.id, project.id)
        assert api_key.key.startswith("eng_")
        assert api_key.key_id  # 应有 key_id
        assert api_key.tenant_id == tenant.id
        assert api_key.project_id == project.id

        # 验证
        verified = cm.verify_api_key(api_key.key)
        assert verified is not None
        assert verified.tenant_id == tenant.id

        # 按 key_id 吊销
        assert cm.revoke_api_key(api_key.key_id)
        assert cm.verify_api_key(api_key.key) is None

    def test_verify_invalid_key(self, cm):
        """无效 Key 验证返回 None"""
        assert cm.verify_api_key("fake_key") is None

    def test_delete_project_cascades_api_keys(self, cm):
        """删除项目时应级联删除 API Key"""
        tenant = cm.register_tenant("测试")
        project = cm.create_project(tenant.id, "项目")
        api_key = cm.generate_api_key(tenant.id, project.id)

        cm.delete_project(project.id, tenant_id=tenant.id)

        # API Key 也应该被删除
        assert cm.verify_api_key(api_key.key) is None

    def test_personal_api_key_flow(self, cm):
        """用户级 API Key 的完整流程：生成 → 验证 → 级联删除"""
        tenant = cm.register_tenant("测试")
        project = cm.create_project(tenant.id, "项目")

        # 生成带 user_id 的
        api_key = cm.generate_api_key(tenant.id, project.id, user_id="lisi")
        assert api_key.key.startswith("eng_")
        assert api_key.user_id == "lisi"

        # 验证提取 user_id 成功
        verified = cm.verify_api_key(api_key.key)
        assert verified.user_id == "lisi"

        # 项目删除后级联注销验证
        cm.delete_project(project.id, tenant_id=tenant.id)
        assert cm.verify_api_key(api_key.key) is None

    def test_list_api_keys(self, cm):
        """列出项目下的 API Key"""
        tenant = cm.register_tenant("测试")
        project = cm.create_project(tenant.id, "项目")
        cm.generate_api_key(tenant.id, project.id)
        cm.generate_api_key(tenant.id, project.id, user_id="user1")

        keys = cm.list_api_keys(project.id)
        assert len(keys) == 2

    def test_delete_tenant(self, cm):
        """删除租户（级联吊销所有 Key）"""
        tenant = cm.register_tenant("测试")
        project = cm.create_project(tenant.id, "项目")
        api_key = cm.generate_api_key(tenant.id, project.id)

        assert cm.delete_tenant(tenant.id)
        assert cm.get_tenant(tenant.id) is None
        assert cm.verify_api_key(api_key.key) is None

    def test_delete_tenant_nonexistent(self, cm):
        """删除不存在的租户返回 False"""
        assert not cm.delete_tenant("nonexistent")
