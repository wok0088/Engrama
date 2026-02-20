"""
渠道管理器测试

测试 ChannelManager 的租户/项目/API Key 管理功能。
"""

import os
import shutil
import tempfile

import pytest

from cortex.store.meta_store import MetaStore
from cortex.channel_manager import ChannelManager


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def cm(tmp_dir):
    """创建 ChannelManager 实例"""
    ms = MetaStore(db_path=os.path.join(tmp_dir, "meta.db"))
    return ChannelManager(meta_store=ms)


class TestChannelManager:
    """ChannelManager 测试用例"""

    def test_register_tenant(self, cm):
        """注册租户"""
        tenant = cm.register_tenant("携程旅行")
        assert tenant.name == "携程旅行"
        assert tenant.id is not None

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
        tenant = cm.register_tenant("测试")
        project = cm.create_project(tenant.id, "酒店 AI")
        assert project.name == "酒店 AI"
        assert project.tenant_id == tenant.id

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
        """删除项目"""
        tenant = cm.register_tenant("测试")
        project = cm.create_project(tenant.id, "待删除")
        assert cm.delete_project(project.id)
        assert cm.get_project(project.id) is None

    def test_api_key_flow(self, cm):
        """完整的 API Key 流程：生成 → 验证 → 吊销"""
        tenant = cm.register_tenant("测试")
        project = cm.create_project(tenant.id, "项目")

        # 生成
        api_key = cm.generate_api_key(tenant.id, project.id)
        assert api_key.key.startswith("ctx_")
        assert api_key.tenant_id == tenant.id
        assert api_key.project_id == project.id

        # 验证
        verified = cm.verify_api_key(api_key.key)
        assert verified is not None
        assert verified.tenant_id == tenant.id

        # 吊销
        assert cm.revoke_api_key(api_key.key)
        assert cm.verify_api_key(api_key.key) is None

    def test_verify_invalid_key(self, cm):
        """无效 Key 验证返回 None"""
        assert cm.verify_api_key("fake_key") is None

    def test_delete_project_cascades_api_keys(self, cm):
        """删除项目时应级联删除 API Key"""
        tenant = cm.register_tenant("测试")
        project = cm.create_project(tenant.id, "项目")
        api_key = cm.generate_api_key(tenant.id, project.id)

        cm.delete_project(project.id)

        # API Key 也应该被删除
        assert cm.verify_api_key(api_key.key) is None
