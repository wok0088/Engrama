"""
渠道管理路由

提供租户注册、项目创建和 API Key 管理的 REST API：
- POST /v1/channels/tenants      — 注册租户
- GET  /v1/channels/tenants      — 列出租户
- POST /v1/channels/projects     — 创建项目
- GET  /v1/channels/projects     — 列出项目
- DELETE /v1/channels/projects/{id} — 删除项目
- POST /v1/channels/api-keys     — 生成 API Key

注意：渠道管理路由不需要 API Key 认证（因为认证本身就依赖渠道管理）。
"""

from fastapi import APIRouter, Request, Query, HTTPException

from cortex.models import (
    RegisterTenantRequest,
    CreateProjectRequest,
    GenerateApiKeyRequest,
    TenantResponse,
    ProjectResponse,
    ApiKeyResponse,
)
from cortex.channel_manager import ChannelManager

router = APIRouter(prefix="/v1/channels", tags=["渠道管理"])


def _get_channel_manager(request: Request) -> ChannelManager:
    """从请求中获取 ChannelManager 实例"""
    return request.app.state.channel_manager


# ----------------------------------------------------------
# 租户管理
# ----------------------------------------------------------

@router.post("/tenants", response_model=TenantResponse, summary="注册租户")
async def register_tenant(body: RegisterTenantRequest, request: Request):
    """注册一个新租户。"""
    cm = _get_channel_manager(request)
    tenant = cm.register_tenant(body.name)
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        created_at=tenant.created_at,
    )


@router.get("/tenants", response_model=list[TenantResponse], summary="列出租户")
def list_tenants(request: Request):
    """列出所有租户。"""
    cm = _get_channel_manager(request)
    tenants = cm.list_tenants()
    return [
        TenantResponse(id=t.id, name=t.name, created_at=t.created_at)
        for t in tenants
    ]


# ----------------------------------------------------------
# 项目管理
# ----------------------------------------------------------

@router.post("/projects", response_model=ProjectResponse, summary="创建项目")
def create_project(body: CreateProjectRequest, request: Request):
    """在指定租户下创建一个新项目。"""
    cm = _get_channel_manager(request)
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
):
    """列出指定租户下的所有项目。"""
    cm = _get_channel_manager(request)
    projects = cm.list_projects(tenant_id)
    return [
        ProjectResponse(
            id=p.id, tenant_id=p.tenant_id, name=p.name, created_at=p.created_at
        )
        for p in projects
    ]


@router.delete("/projects/{project_id}", summary="删除项目")
def delete_project(project_id: str, request: Request):
    """删除指定项目及其关联的 API Key。"""
    cm = _get_channel_manager(request)
    success = cm.delete_project(project_id)
    if not success:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"detail": "删除成功", "id": project_id}


# ----------------------------------------------------------
# API Key 管理
# ----------------------------------------------------------

@router.post("/api-keys", response_model=ApiKeyResponse, summary="生成 API Key")
def generate_api_key(body: GenerateApiKeyRequest, request: Request):
    """
    为指定的 tenant + project 生成一个 API Key。

    ⚠️ API Key 只在创建时展示一次，请妥善保存。
    """
    cm = _get_channel_manager(request)
    try:
        api_key = cm.generate_api_key(body.tenant_id, body.project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiKeyResponse(
        key=api_key.key,
        tenant_id=api_key.tenant_id,
        project_id=api_key.project_id,
        created_at=api_key.created_at,
    )
