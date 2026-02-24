"""
存储层测试

测试 VectorStore 和 MetaStore 的核心功能。
"""

import os

import pytest

from engrama.models import MemoryFragment, MemoryType, Role
from engrama.store.qdrant_store import QdrantStore
from engrama.store.base_meta_store import BaseMetaStore
from engrama.store import create_meta_store


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def meta_store():
    """创建 MetaStore 实例"""
    return create_meta_store()


@pytest.fixture(scope="module")
def vector_store(meta_store):
    return QdrantStore(meta_store=meta_store)


# ============================================================
# QdrantStore 测试
# ============================================================

class TestQdrantStore:
    """QdrantStore 测试用例"""

    def test_add_and_list(self, vector_store):
        """添加记忆后能成功列出"""
        fragment = MemoryFragment(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="生日是 1990-03-15",
            memory_type=MemoryType.FACTUAL,
        )
        vector_store.add(fragment)

        results = vector_store.list_memories("t1", "p1", "u1")
        assert len(results) == 1
        assert results[0]["content"] == "生日是 1990-03-15"
        assert results[0]["memory_type"] == "factual"

    def test_search(self, vector_store):
        """语义搜索能找到相关记忆"""
        # 添加几条不同主题的记忆
        memories = [
            ("喜欢吃四川火锅", MemoryType.PREFERENCE),
            ("每天早上 7 点起床", MemoryType.FACTUAL),
            ("不喜欢太辣的食物", MemoryType.PREFERENCE),
        ]
        for content, mt in memories:
            fragment = MemoryFragment(
                tenant_id="t1", project_id="p1", user_id="u1",
                content=content, memory_type=mt,
            )
            vector_store.add(fragment)

        # 搜索与"饮食"相关的内容
        results = vector_store.search("t1", "p1", "u1", query="吃东西的偏好")
        assert len(results) > 0
        # 搜索结果应该包含 score 字段
        assert "score" in results[0]

    def test_search_with_type_filter(self, vector_store):
        """搜索时可以按类型过滤"""
        vector_store.add(MemoryFragment(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="生日是 3 月份", memory_type=MemoryType.FACTUAL,
        ))
        vector_store.add(MemoryFragment(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="喜欢收到生日礼物", memory_type=MemoryType.PREFERENCE,
        ))

        # 只搜索 factual 类型
        results = vector_store.search(
            "t1", "p1", "u1", query="生日",
            memory_type=MemoryType.FACTUAL,
        )
        assert all(r["memory_type"] == "factual" for r in results)

    def test_session_history(self, vector_store):
        """获取会话历史并按时间排序"""
        import time

        for i, (content, role) in enumerate([
            ("你好", Role.USER),
            ("你好！有什么可以帮你？", Role.ASSISTANT),
            ("帮我分析一下八字", Role.USER),
        ]):
            time.sleep(0.01)  # 确保时间戳不同
            vector_store.add(MemoryFragment(
                tenant_id="t1", project_id="p1", user_id="u1",
                content=content, memory_type=MemoryType.SESSION,
                role=role, session_id="s1",
            ))

        history = vector_store.get_by_session("t1", "p1", "u1", "s1")
        assert len(history) == 3
        assert history[0]["content"] == "你好"
        assert history[2]["content"] == "帮我分析一下八字"

    def test_delete(self, vector_store):
        """删除指定记忆"""
        fragment = MemoryFragment(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="要删除的记忆", memory_type=MemoryType.FACTUAL,
        )
        vector_store.add(fragment)

        assert vector_store.delete("t1", "p1", "u1", fragment.id)
        results = vector_store.list_memories("t1", "p1", "u1")
        assert len(results) == 0

    def test_user_isolation(self, vector_store):
        """不同用户的数据隔离"""
        vector_store.add(MemoryFragment(
            tenant_id="t1", project_id="p1", user_id="user_a",
            content="用户 A 的记忆", memory_type=MemoryType.FACTUAL,
        ))
        vector_store.add(MemoryFragment(
            tenant_id="t1", project_id="p1", user_id="user_b",
            content="用户 B 的记忆", memory_type=MemoryType.FACTUAL,
        ))

        a_memories = vector_store.list_memories("t1", "p1", "user_a")
        b_memories = vector_store.list_memories("t1", "p1", "user_b")
        assert len(a_memories) == 1
        assert len(b_memories) == 1
        assert a_memories[0]["content"] == "用户 A 的记忆"
        assert b_memories[0]["content"] == "用户 B 的记忆"

    def test_stats(self, vector_store):
        """统计信息正确"""
        vector_store.add(MemoryFragment(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="事实 1", memory_type=MemoryType.FACTUAL,
        ))
        vector_store.add(MemoryFragment(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="偏好 1", memory_type=MemoryType.PREFERENCE,
        ))
        vector_store.add(MemoryFragment(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="偏好 2", memory_type=MemoryType.PREFERENCE,
        ))

        stats = vector_store.get_stats("t1", "p1", "u1")
        assert stats["total"] == 3
        assert stats["by_type"]["factual"] == 1
        assert stats["by_type"]["preference"] == 2

    def test_increment_hit_count(self, vector_store):
        """hit_count 递增"""
        fragment = MemoryFragment(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="测试 hit count", memory_type=MemoryType.FACTUAL,
        )
        vector_store.add(fragment)

        vector_store.increment_hit_count("t1", "p1", "u1", fragment.id)
        vector_store.increment_hit_count("t1", "p1", "u1", fragment.id)

        results = vector_store.list_memories("t1", "p1", "u1")
        assert results[0]["hit_count"] == 2

    def test_batch_increment_hit_count(self, vector_store):
        """batch_increment_hit_count 批量递增"""
        f1 = MemoryFragment(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="记忆 1", memory_type=MemoryType.FACTUAL,
        )
        f2 = MemoryFragment(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="记忆 2", memory_type=MemoryType.FACTUAL,
        )
        vector_store.add(f1)
        vector_store.add(f2)

        vector_store.batch_increment_hit_count("t1", "p1", [f1.id, f2.id])

        results = vector_store.list_memories("t1", "p1", "u1")
        hit_counts = {r["id"]: r["hit_count"] for r in results}
        assert hit_counts[f1.id] == 1
        assert hit_counts[f2.id] == 1



# ============================================================
# MetaStore 测试
# ============================================================

class TestMetaStore:
    """MetaStore 测试用例"""

    def test_create_and_get_tenant(self, meta_store):
        """创建租户后能获取到"""
        tenant = meta_store.create_tenant("测试公司")
        assert tenant.name == "测试公司"

        fetched = meta_store.get_tenant(tenant.id)
        assert fetched is not None
        assert fetched.name == "测试公司"

    def test_list_tenants(self, meta_store):
        """列出所有租户"""
        meta_store.create_tenant("公司 A")
        meta_store.create_tenant("公司 B")

        tenants = meta_store.list_tenants()
        assert len(tenants) == 2

    def test_create_project(self, meta_store):
        """在租户下创建项目"""
        tenant = meta_store.create_tenant("测试公司")
        project = meta_store.create_project(tenant.id, "酒店 AI")

        assert project.name == "酒店 AI"
        assert project.tenant_id == tenant.id

    def test_create_project_invalid_tenant(self, meta_store):
        """无效的租户 ID 应报错"""
        with pytest.raises(ValueError, match="租户不存在"):
            meta_store.create_project("invalid_id", "测试项目")

    def test_delete_project(self, meta_store):
        """删除项目（需传入 tenant_id）"""
        tenant = meta_store.create_tenant("测试")
        project = meta_store.create_project(tenant.id, "待删除")
        assert meta_store.delete_project(project.id, tenant_id=tenant.id)
        assert meta_store.get_project(project.id) is None

    def test_delete_project_wrong_tenant(self, meta_store):
        """用错误 tenant_id 删除项目应失败"""
        tenant = meta_store.create_tenant("测试")
        project = meta_store.create_project(tenant.id, "项目")
        assert not meta_store.delete_project(project.id, tenant_id="wrong_tenant")
        # 项目仍然存在
        assert meta_store.get_project(project.id) is not None

    def test_api_key_lifecycle(self, meta_store):
        """API Key 的生成、验证、吊销（使用哈希存储）"""
        tenant = meta_store.create_tenant("测试")
        project = meta_store.create_project(tenant.id, "项目")

        # 生成
        api_key = meta_store.generate_api_key(tenant.id, project.id)
        assert api_key.key.startswith("eng_")
        assert api_key.key_id  # key_id 应非空
        assert api_key.key_hash  # key_hash 应非空

        # 验证（使用原始 Key）
        verified = meta_store.verify_api_key(api_key.key)
        assert verified is not None
        assert verified.tenant_id == tenant.id
        assert verified.project_id == project.id
        assert verified.key_id == api_key.key_id

        # 按 key_id 吊销
        assert meta_store.revoke_api_key(api_key.key_id)
        assert meta_store.verify_api_key(api_key.key) is None

    def test_personal_api_key_lifecycle(self, meta_store):
        """用户级 API Key 的生成与验证"""
        tenant = meta_store.create_tenant("测试")
        project = meta_store.create_project(tenant.id, "项目")

        api_key = meta_store.generate_api_key(tenant.id, project.id, user_id="lisi")
        assert api_key.user_id == "lisi"

        verified = meta_store.verify_api_key(api_key.key)
        assert verified.user_id == "lisi"

    def test_invalid_api_key(self, meta_store):
        """无效的 API Key 验证返回 None"""
        assert meta_store.verify_api_key("invalid_key") is None

    def test_list_api_keys(self, meta_store):
        """列出项目下的 API Key"""
        tenant = meta_store.create_tenant("测试")
        project = meta_store.create_project(tenant.id, "项目")

        k1 = meta_store.generate_api_key(tenant.id, project.id)
        k2 = meta_store.generate_api_key(tenant.id, project.id, user_id="user1")

        keys = meta_store.list_api_keys(project.id)
        assert len(keys) == 2
        # 列表不应包含完整 Key 或哈希
        for k in keys:
            assert "key" not in k or k.get("key") is None
            assert "key_hash" not in k

    def test_delete_tenant(self, meta_store):
        """删除租户：级联吊销 Key + 删除项目"""
        tenant = meta_store.create_tenant("测试")
        project = meta_store.create_project(tenant.id, "项目")
        api_key = meta_store.generate_api_key(tenant.id, project.id)

        assert meta_store.delete_tenant(tenant.id)

        # 租户、项目不存在
        assert meta_store.get_tenant(tenant.id) is None
        assert meta_store.get_project(project.id) is None
        # API Key 失效
        assert meta_store.verify_api_key(api_key.key) is None

    def test_delete_tenant_nonexistent(self, meta_store):
        """删除不存在的租户返回 False"""
        assert not meta_store.delete_tenant("nonexistent")


# ============================================================
# P2 新增测试
# ============================================================

class TestUpdateWhitelist:
    """update_memory_fragment 列名白名单测试"""

    def test_whitelist_rejects_invalid_column(self, meta_store):
        """传入非法列名应抛出 ValueError"""
        from engrama.models import MemoryFragment, MemoryType
        fragment = MemoryFragment(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="测试", memory_type=MemoryType.FACTUAL,
        )
        meta_store.add_memory_fragment(fragment)

        with pytest.raises(ValueError, match="不允许更新字段"):
            meta_store.update_memory_fragment(fragment.id, {"id": "hacked"})

    def test_whitelist_allows_valid_columns(self, meta_store):
        """合法列名应正常更新"""
        from engrama.models import MemoryFragment, MemoryType
        fragment = MemoryFragment(
            tenant_id="t1", project_id="p1", user_id="u1",
            content="原始内容", memory_type=MemoryType.FACTUAL,
        )
        meta_store.add_memory_fragment(fragment)

        result = meta_store.update_memory_fragment(
            fragment.id, {"content": "新内容", "tags": ["tag1"]}
        )
        assert result is True

        updated = meta_store.get_memory_fragment(fragment.id)
        assert updated["content"] == "新内容"
        assert updated["tags"] == ["tag1"]


class TestUserIsolation:
    """跨用户数据隔离深度测试"""

    def test_update_cross_user_fails(self, vector_store, meta_store):
        """用户 A 不能通过 update 修改用户 B 的记忆"""
        from engrama.models import MemoryFragment, MemoryType
        from engrama.memory_manager import MemoryManager

        mm = MemoryManager(vector_store=vector_store, meta_store=meta_store)

        frag_b = mm.add(
            tenant_id="t1", project_id="p1", user_id="bob",
            content="Bob 的秘密", memory_type=MemoryType.FACTUAL,
        )

        # 用 alice 的身份尝试更新 bob 的记忆
        result = mm.update(
            tenant_id="t1", project_id="p1", user_id="alice",
            fragment_id=frag_b.id, content="被篡改",
        )
        assert result is None  # 应返回 None（未找到/无权）

        # 验证 bob 的记忆未被修改
        original = meta_store.get_memory_fragment(frag_b.id)
        assert original["content"] == "Bob 的秘密"

    def test_delete_cross_user_fails(self, vector_store, meta_store):
        """用户 A 不能删除用户 B 的记忆"""
        from engrama.models import MemoryFragment, MemoryType
        from engrama.memory_manager import MemoryManager

        mm = MemoryManager(vector_store=vector_store, meta_store=meta_store)

        frag_b = mm.add(
            tenant_id="t1", project_id="p1", user_id="bob",
            content="Bob 的数据", memory_type=MemoryType.FACTUAL,
        )

        # 用 alice 的身份尝试删除 bob 的记忆
        result = mm.delete(
            tenant_id="t1", project_id="p1", user_id="alice",
            fragment_id=frag_b.id,
        )
        assert result is False

        # 验证 bob 的记忆仍存在
        original = meta_store.get_memory_fragment(frag_b.id)
        assert original is not None
