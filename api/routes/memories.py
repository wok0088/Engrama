"""
记忆路由

提供记忆的增删改查搜 REST API：
- POST   /v1/memories         — 添加记忆
- POST   /v1/memories/search  — 语义搜索
- GET    /v1/memories         — 列出记忆
- PUT    /v1/memories/{id}    — 更新记忆
- DELETE /v1/memories/{id}    — 删除记忆
- GET    /v1/sessions/{session_id}/history — 获取会话历史
- GET    /v1/users/{user_id}/stats        — 获取统计信息
"""

from typing import Optional

from fastapi import APIRouter, Request, Query, HTTPException, Depends

from engrama.models import (
    AddMemoryRequest,
    UpdateMemoryRequest,
    SearchMemoryRequest,
    MemoryResponse,
    SearchResultResponse,
    MemoryType,
    HistoryResponse,
    StatsResponse,
)
from engrama.memory_manager import MemoryManager

router = APIRouter(prefix="/v1", tags=["记忆管理"])


def get_memory_manager(request: Request) -> MemoryManager:
    """从请求中获取 MemoryManager 实例"""
    return request.app.state.memory_manager


def resolve_user_id(request: Request, user_id: str = Query(default="", description="用户 ID（用户级 Key 可不传）")) -> str:
    """
    解析最终使用的 user_id

    优先级：
    1. API Key 绑定的 user_id（不可覆盖）
    2. 请求中传入的 user_id
    """
    bound_user_id = getattr(request.state, "bound_user_id", None)

    if bound_user_id:
        if user_id and user_id != bound_user_id:
            raise HTTPException(
                status_code=403,
                detail=f"此 API Key 已绑定用户 '{bound_user_id}'，不允许操作其他用户数据",
            )
        return bound_user_id
    else:
        if not user_id:
            raise HTTPException(
                status_code=400,
                detail="缺少 user_id 参数（项目级 API Key 必须传入 user_id）",
            )
        return user_id


def resolve_user_id_from_body(request: Request, body_user_id: str) -> str:
    """从请求体中解析 user_id"""
    bound_user_id = getattr(request.state, "bound_user_id", None)

    if bound_user_id:
        if body_user_id and body_user_id != bound_user_id:
            raise HTTPException(
                status_code=403,
                detail=f"此 API Key 已绑定用户 '{bound_user_id}'，不允许操作其他用户数据",
            )
        return bound_user_id
    else:
        if not body_user_id:
            raise HTTPException(
                status_code=400,
                detail="缺少 user_id 参数（项目级 API Key 必须传入 user_id）",
            )
        return body_user_id


def _dict_to_response(item: dict) -> MemoryResponse:
    """将字典转为 MemoryResponse"""
    return MemoryResponse(
        id=item["id"],
        user_id=item["user_id"],
        content=item["content"],
        memory_type=item["memory_type"],
        role=item.get("role"),
        session_id=item.get("session_id"),
        tags=item.get("tags", []),
        hit_count=item.get("hit_count", 0),
        importance=item.get("importance", 0.0),
        created_at=item["created_at"],
        updated_at=item["updated_at"],
        metadata=item.get("metadata"),
        score=item.get("score"),
    )


# ----------------------------------------------------------
# 记忆 CRUD
# ----------------------------------------------------------

@router.post("/memories", response_model=MemoryResponse, summary="添加记忆")
def add_memory(
    body: AddMemoryRequest,
    request: Request,
    manager: MemoryManager = Depends(get_memory_manager),
):
    """
    添加一条记忆片段。

    需要通过 X-API-Key 认证，tenant_id 和 project_id 从 API Key 自动获取。
    """
    user_id = resolve_user_id_from_body(request, body.user_id)
    fragment = manager.add(
        tenant_id=request.state.tenant_id,
        project_id=request.state.project_id,
        user_id=user_id,
        content=body.content,
        memory_type=body.memory_type,
        role=body.role,
        session_id=body.session_id,
        tags=body.tags,
        importance=body.importance,
        metadata=body.metadata,
    )
    return MemoryResponse(**fragment.to_response_dict())


@router.post("/memories/search", response_model=SearchResultResponse, summary="语义搜索")
def search_memories(
    body: SearchMemoryRequest,
    request: Request,
    manager: MemoryManager = Depends(get_memory_manager),
):
    """
    语义搜索记忆。

    使用 POST 而非 GET，因为搜索条件可能很复杂。
    """
    user_id = resolve_user_id_from_body(request, body.user_id)
    results = manager.search(
        tenant_id=request.state.tenant_id,
        project_id=request.state.project_id,
        user_id=user_id,
        query=body.query,
        limit=body.limit,
        memory_type=body.memory_type,
        session_id=body.session_id,
    )
    items = [_dict_to_response(r) for r in results]
    return SearchResultResponse(results=items, count=len(items))


@router.get("/memories", response_model=list[MemoryResponse], summary="列出记忆")
def list_memories(
    request: Request,
    user_id: str = Depends(resolve_user_id),
    memory_type: Optional[MemoryType] = Query(default=None, description="按类型过滤"),
    limit: int = Query(default=100, ge=1, le=1000, description="返回数量上限"),
    offset: int = Query(default=0, ge=0, description="分页偏移量"),
    manager: MemoryManager = Depends(get_memory_manager),
):
    """列出指定用户的记忆片段，可按类型过滤。"""
    results = manager.list_memories(
        tenant_id=request.state.tenant_id,
        project_id=request.state.project_id,
        user_id=user_id,
        memory_type=memory_type,
        limit=limit,
        offset=offset,
    )
    return [_dict_to_response(r) for r in results]


@router.put("/memories/{fragment_id}", response_model=MemoryResponse, summary="更新记忆")
def update_memory(
    fragment_id: str,
    body: UpdateMemoryRequest,
    request: Request,
    manager: MemoryManager = Depends(get_memory_manager),
):
    """
    更新指定记忆片段。

    只需传入要更新的字段，未传入的字段保持不变。
    如果更新了 content，会自动重新向量化。
    """
    user_id = resolve_user_id_from_body(request, body.user_id)
    result = manager.update(
        tenant_id=request.state.tenant_id,
        project_id=request.state.project_id,
        user_id=user_id,
        fragment_id=fragment_id,
        content=body.content,
        tags=body.tags,
        importance=body.importance,
        metadata=body.metadata,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="记忆片段不存在")
    return _dict_to_response(result)


@router.delete("/memories/{fragment_id}", summary="删除记忆")
def delete_memory(
    fragment_id: str,
    request: Request,
    user_id: str = Depends(resolve_user_id),
    manager: MemoryManager = Depends(get_memory_manager),
):
    """删除指定的记忆片段。"""
    success = manager.delete(
        tenant_id=request.state.tenant_id,
        project_id=request.state.project_id,
        user_id=user_id,
        fragment_id=fragment_id,
    )
    if not success:
        raise HTTPException(status_code=404, detail="记忆片段不存在")
    return {"detail": "删除成功", "id": fragment_id}


# ----------------------------------------------------------
# 会话历史
# ----------------------------------------------------------

@router.get(
    "/sessions/{session_id}/history",
    response_model=HistoryResponse,
    summary="获取会话历史",
)
def get_session_history(
    session_id: str,
    request: Request,
    user_id: str = Depends(resolve_user_id),
    limit: int = Query(default=100, ge=1, le=1000, description="返回数量上限"),
    offset: int = Query(default=0, ge=0, description="分页偏移量"),
    manager: MemoryManager = Depends(get_memory_manager),
):
    """获取指定会话的消息历史，按时间排序。"""
    results = manager.get_history(
        tenant_id=request.state.tenant_id,
        project_id=request.state.project_id,
        user_id=user_id,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    messages = [_dict_to_response(r) for r in results]
    return HistoryResponse(
        session_id=session_id,
        messages=messages,
        count=len(messages),
    )


# ----------------------------------------------------------
# 统计信息
# ----------------------------------------------------------

# ⚠️ 路由顺序依赖：/users/me/stats 必须在 /users/{user_id}/stats 之前注册，
# 否则 "me" 会被 FastAPI 当作 {user_id} 路径参数匹配。
@router.get(
    "/users/me/stats",
    response_model=StatsResponse,
    summary="获取当前(绑定)用户的统计信息",
)
def get_my_stats(
    request: Request,
    manager: MemoryManager = Depends(get_memory_manager),
):
    """获取当前绑定用户（需用户级 Key）的记忆统计信息。"""
    # 不允许项目级 Key 访问 /users/me/stats (因为不知道是谁的 stats)
    bound_user_id = getattr(request.state, "bound_user_id", None)
    if not bound_user_id:
        raise HTTPException(
            status_code=400,
            detail="缺少 user_id 参数（项目级 API Key 不能调用 /users/me/stats，必须指定具体的用户 ID）",
        )
    stats = manager.get_stats(
        tenant_id=request.state.tenant_id,
        project_id=request.state.project_id,
        user_id=bound_user_id,
    )
    return StatsResponse(
        user_id=bound_user_id,
        total_memories=stats["total"],
        by_type=stats["by_type"],
    )


@router.get(
    "/users/{user_id}/stats",
    response_model=StatsResponse,
    summary="获取特定用户的统计信息",
)
def get_user_stats(
    user_id: str,
    request: Request,
    manager: MemoryManager = Depends(get_memory_manager),
):
    """获取指定用户的记忆统计信息。"""
    stats = manager.get_stats(
        tenant_id=request.state.tenant_id,
        project_id=request.state.project_id,
        user_id=user_id,
    )
    return StatsResponse(
        user_id=user_id,
        total_memories=stats["total"],
        by_type=stats["by_type"],
    )
