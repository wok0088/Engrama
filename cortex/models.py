"""
Engrama 数据模型

定义记忆系统的核心数据结构和 API Schema。
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================
# 核心枚举
# ============================================================

class MemoryType(str, Enum):
    """记忆类型"""
    FACTUAL = "factual"        # 事实记忆：客观事实信息
    PREFERENCE = "preference"  # 偏好记忆：主观喜好
    EPISODIC = "episodic"      # 经历记忆：具体交互事件
    SESSION = "session"        # 会话记忆：对话上下文消息


class Role(str, Enum):
    """消息角色（仅 session 类型使用）"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# ============================================================
# 核心数据模型
# ============================================================

def _generate_id() -> str:
    """生成唯一 ID"""
    return uuid.uuid4().hex


def _now() -> datetime:
    """获取当前 UTC 时间"""
    return datetime.now(timezone.utc)


class MemoryFragment(BaseModel):
    """
    记忆片段 — Engrama 的核心数据单元

    每个记忆片段归属于 tenant → project → user 三层组织结构。
    """
    id: str = Field(default_factory=_generate_id, description="唯一 ID")
    tenant_id: str = Field(description="租户 ID")
    project_id: str = Field(description="项目 ID")
    user_id: str = Field(description="用户 ID")
    content: str = Field(description="记忆内容")
    memory_type: MemoryType = Field(description="记忆类型")
    role: Optional[Role] = Field(default=None, description="消息角色（仅 session 类型）")
    session_id: Optional[str] = Field(default=None, description="会话 ID（仅 session 类型）")
    tags: list[str] = Field(default_factory=list, description="标签")
    hit_count: int = Field(default=0, description="被检索次数（用于排序优化和智能淘汰）")
    importance: float = Field(default=0.0, description="重要度评分（用于检索排序和缓存预热）")
    created_at: datetime = Field(default_factory=_now, description="创建时间")
    updated_at: datetime = Field(default_factory=_now, description="更新时间")
    metadata: Optional[dict] = Field(default=None, description="扩展元数据")


class Tenant(BaseModel):
    """租户 — 最顶层的组织单位（如企业或个人开发者）"""
    id: str = Field(default_factory=_generate_id, description="租户 ID")
    name: str = Field(description="租户名称")
    created_at: datetime = Field(default_factory=_now, description="创建时间")


class Project(BaseModel):
    """项目 — 租户下的业务线（如"酒店 AI"、"机票 AI"）"""
    id: str = Field(default_factory=_generate_id, description="项目 ID")
    tenant_id: str = Field(description="所属租户 ID")
    name: str = Field(description="项目名称")
    created_at: datetime = Field(default_factory=_now, description="创建时间")


class ApiKey(BaseModel):
    """API Key — 用于认证和路由请求到对应的 tenant/project

    支持两种级别：
    - 项目级 Key（user_id=None）：B 端，调用方必须传 user_id
    - 用户级 Key（user_id 有值）：C 端，user_id 自动绑定，不可覆盖
    """
    key: str = Field(description="API Key 值")
    tenant_id: str = Field(description="所属租户 ID")
    project_id: str = Field(description="所属项目 ID")
    user_id: Optional[str] = Field(default=None, description="绑定的用户 ID（None 为项目级 Key）")
    created_at: datetime = Field(default_factory=_now, description="创建时间")
    is_active: bool = Field(default=True, description="是否激活")


# ============================================================
# API 请求/响应 Schema
# ============================================================

class AddMemoryRequest(BaseModel):
    """添加记忆请求"""
    user_id: Optional[str] = Field(default="", description="用户 ID（用户级 Key 可不传）", max_length=100)
    content: str = Field(description="记忆内容", min_length=1, max_length=10000)
    memory_type: MemoryType = Field(description="记忆类型")
    role: Optional[Role] = Field(default=None, description="消息角色（仅 session 类型）")
    session_id: Optional[str] = Field(default=None, description="会话 ID", max_length=100)
    tags: list[str] = Field(default_factory=list, description="标签", max_length=20)
    importance: float = Field(default=0.0, ge=0.0, le=1.0, description="重要度评分")
    metadata: Optional[dict] = Field(default=None, description="扩展元数据")


class SearchMemoryRequest(BaseModel):
    """搜索记忆请求"""
    user_id: Optional[str] = Field(default="", description="用户 ID（用户级 Key 可不传）", max_length=100)
    query: str = Field(description="搜索查询", min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=100, description="返回数量上限")
    memory_type: Optional[MemoryType] = Field(default=None, description="按类型过滤")
    session_id: Optional[str] = Field(default=None, description="按会话过滤")


class MemoryResponse(BaseModel):
    """记忆响应"""
    id: str
    user_id: str
    content: str
    memory_type: MemoryType
    role: Optional[Role] = None
    session_id: Optional[str] = None
    tags: list[str] = []
    hit_count: int = 0
    importance: float = 0.0
    created_at: datetime
    updated_at: datetime
    metadata: Optional[dict] = None
    score: Optional[float] = Field(default=None, description="搜索相似度分数（仅搜索结果包含）")


class SearchResultResponse(BaseModel):
    """搜索结果响应"""
    results: list[MemoryResponse]
    total: int


class RegisterTenantRequest(BaseModel):
    """注册租户请求"""
    name: str = Field(description="租户名称", min_length=1, max_length=100)


class CreateProjectRequest(BaseModel):
    """创建项目请求"""
    tenant_id: str = Field(description="租户 ID")
    name: str = Field(description="项目名称", min_length=1, max_length=100)


class GenerateApiKeyRequest(BaseModel):
    """生成 API Key 请求"""
    tenant_id: str = Field(description="租户 ID")
    project_id: str = Field(description="项目 ID")
    user_id: Optional[str] = Field(default=None, description="可选：绑定用户 ID（为空则生成项目级 Key）")


class TenantResponse(BaseModel):
    """租户响应"""
    id: str
    name: str
    created_at: datetime


class ProjectResponse(BaseModel):
    """项目响应"""
    id: str
    tenant_id: str
    name: str
    created_at: datetime


class ApiKeyResponse(BaseModel):
    """API Key 响应"""
    key: str
    tenant_id: str
    project_id: str
    user_id: Optional[str] = None
    created_at: datetime


class StatsResponse(BaseModel):
    """统计信息响应"""
    user_id: str
    total_memories: int
    by_type: dict[str, int]


class HistoryResponse(BaseModel):
    """会话历史响应"""
    session_id: str
    messages: list[MemoryResponse]
    total: int


class UpdateMemoryRequest(BaseModel):
    """更新记忆请求"""
    user_id: Optional[str] = Field(default="", description="用户 ID（用户级 Key 可不传）", max_length=100)
    content: Optional[str] = Field(default=None, description="新的记忆内容", max_length=10000)
    tags: Optional[list[str]] = Field(default=None, description="新的标签", max_length=20)
    importance: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="新的重要度评分")
    metadata: Optional[dict] = Field(default=None, description="新的扩展元数据")
