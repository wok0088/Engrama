"""
渠道管理路由

提供租户注册、项目创建和 API Key 管理的 REST API：
- POST   /v1/channels/tenants         — 注册租户
- GET    /v1/channels/tenants         — 列出租户
- DELETE /v1/channels/tenants/{id}    — 删除租户
- POST   /v1/channels/projects        — 创建项目
- GET    /v1/channels/projects        — 列出项目
- DELETE /v1/channels/projects/{id}   — 删除项目
- POST   /v1/channels/api-keys        — 生成 API Key
- GET    /v1/channels/api-keys        — 列出 API Key
- DELETE /v1/channels/api-keys/{key_id} — 吊销 API Key

注意：渠道管理路由不需要 API Key 认证（因为认证本身就依赖渠道管理）。
"""

from fastapi import APIRouter, Request, Query, HTTPException, Depends

from engrama.models import (
    RegisterTenantRequest,
    CreateProjectRequest,
    GenerateApiKeyRequest,
    TenantResponse,
    ProjectResponse,
    ApiKeyResponse,
    ApiKeyListItem,
)
from engrama.channel_manager import ChannelManager

router = APIRouter(prefix="/v1/channels", tags=["渠道管理"])


def get_channel_manager(request: Request) -> ChannelManager:
    """从请求中获取 ChannelManager 实例"""
    return request.app.state.channel_manager


# ----------------------------------------------------------
# 租户管理
# ----------------------------------------------------------

@router.post("/tenants", response_model=TenantResponse, summary="注册租户")
def register_tenant(
    body: RegisterTenantRequest,
    request: Request,
    cm: ChannelManager = Depends(get_channel_manager),
):
    """注册一个新租户。"""
    tenant = cm.register_tenant(body.name)
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        created_at=tenant.created_at,
    )


@router.get("/tenants", response_model=list[TenantResponse], summary="列出租户")
def list_tenants(
    request: Request,
    cm: ChannelManager = Depends(get_channel_manager),
):
    """列出所有租户。"""
    tenants = cm.list_tenants()
    return [
        TenantResponse(id=t.id, name=t.name, created_at=t.created_at)
        for t in tenants
    ]


@router.delete("/tenants/{tenant_id}", summary="删除租户")
def delete_tenant(
    tenant_id: str,
    request: Request,
    cm: ChannelManager = Depends(get_channel_manager),
):
    """
    删除指定租户及其所有项目和 API Key。

    注意：不清理 ChromaDB 向量数据，仅通过 API Key 失效让数据"不可访问"，
    作为误删保护机制。
    """
    success = cm.delete_tenant(tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="租户不存在")
    return {"detail": "删除成功", "id": tenant_id}


# ----------------------------------------------------------
# 项目管理
# ----------------------------------------------------------

@router.post("/projects", response_model=ProjectResponse, summary="创建项目")
def create_project(
    body: CreateProjectRequest,
    request: Request,
    cm: ChannelManager = Depends(get_channel_manager),
):
    """在指定租户下创建一个新项目。"""
    try:
        project = cm.create_project(body.tenant_id, body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ProjectResponse(
        id=project.id,
        tenant_id=project.tenant_id,
        name=project.name,
        created_at=project.created_at,
    )


@router.get("/projects", response_model=list[ProjectResponse], summary="列出项目")
def list_projects(
    request: Request,
    tenant_id: str = Query(description="租户 ID"),
    cm: ChannelManager = Depends(get_channel_manager),
):
    """列出指定租户下的所有项目。"""
    projects = cm.list_projects(tenant_id)
    return [
        ProjectResponse(
            id=p.id, tenant_id=p.tenant_id, name=p.name, created_at=p.created_at
        )
        for p in projects
    ]


@router.delete("/projects/{project_id}", summary="删除项目")
def delete_project(
    project_id: str,
    request: Request,
    tenant_id: str = Query(description="租户 ID（验证项目归属）"),
    cm: ChannelManager = Depends(get_channel_manager),
):
    """删除指定项目及其关联的 API Key。需传入 tenant_id 验证归属关系。"""
    success = cm.delete_project(project_id, tenant_id=tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="项目不存在或不属于该租户")
    return {"detail": "删除成功", "id": project_id}


# ----------------------------------------------------------
# API Key 管理
# ----------------------------------------------------------

@router.post("/api-keys", response_model=ApiKeyResponse, summary="生成 API Key")
def generate_api_key(
    body: GenerateApiKeyRequest,
    request: Request,
    cm: ChannelManager = Depends(get_channel_manager),
):
    """
    为指定的 tenant + project 生成一个 API Key。

    可选传入 user_id 生成用户级 Key（C 端），不传则为项目级 Key（B 端）。
    ⚠️ API Key 只在创建时展示一次，请妥善保存。
    """
    try:
        api_key = cm.generate_api_key(body.tenant_id, body.project_id, user_id=body.user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiKeyResponse(
        key=api_key.key,
        key_id=api_key.key_id,
        tenant_id=api_key.tenant_id,
        project_id=api_key.project_id,
        user_id=api_key.user_id,
        created_at=api_key.created_at,
    )


@router.get("/api-keys", response_model=list[ApiKeyListItem], summary="列出 API Key")
def list_api_keys(
    request: Request,
    project_id: str = Query(description="项目 ID"),
    cm: ChannelManager = Depends(get_channel_manager),
):
    """列出指定项目下的所有 API Key（不暴露完整 Key 值）。"""
    keys = cm.list_api_keys(project_id)
    return [
        ApiKeyListItem(
            key_id=k["key_id"],
            tenant_id=k["tenant_id"],
            project_id=k["project_id"],
            user_id=k["user_id"],
            created_at=k["created_at"],
            is_active=k["is_active"],
        )
        for k in keys
    ]


@router.delete("/api-keys/{key_id}", summary="吊销 API Key")
def revoke_api_key(
    key_id: str,
    request: Request,
    cm: ChannelManager = Depends(get_channel_manager),
):
    """按 key_id 吊销指定的 API Key。"""
    success = cm.revoke_api_key(key_id)
    if not success:
        raise HTTPException(status_code=404, detail="API Key 不存在或已吊销")
    return {"detail": "吊销成功", "key_id": key_id}
