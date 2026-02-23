"""
Engrama MCP Server

将 Engrama 的记忆管理能力通过 MCP (Model Context Protocol) 暴露给 AI 模型。
AI 模型（如 Claude、Cursor 等）可以通过 MCP 协议直接调用 Engrama 的记忆功能，
自主决定何时存取用户记忆。

MCP Server 复用 Engrama 的业务层（MemoryManager），不引入新的存储逻辑。

使用方式：
    # stdio 模式（Claude Desktop / Cursor 等 MCP 客户端）
    python -m mcp_server.server

    # 或者通过 SSE 模式（HTTP 远程访问）
    python -m mcp_server.server --transport sse --port 8001
"""

import argparse
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from cortex.logger import get_logger
from cortex.models import MemoryType, Role
from cortex.store.vector_store import VectorStore
from cortex.store.meta_store import MetaStore
from cortex.memory_manager import MemoryManager

logger = get_logger(__name__)

# ----------------------------------------------------------
# 初始化 MCP Server 和 Engrama 业务层
# ----------------------------------------------------------

mcp = FastMCP(
    "engrama",
    instructions=(
        "Engrama 是一个 AI 记忆中间件。你可以使用以下工具来存储和检索用户记忆。"
        "在对话中，当你了解到关于用户的重要信息（偏好、事实、经历等）时，"
        "应该主动调用 add_memory 存储。当需要回忆用户信息时，调用 search_memory。"
    ),
)

# 初始化存储和管理器（全局单例）
_vector_store = VectorStore()
_meta_store = MetaStore()
_memory_manager = MemoryManager(vector_store=_vector_store, meta_store=_meta_store)

logger.info("Engrama MCP Server 初始化完成")


# ----------------------------------------------------------
# MCP Tools — 记忆管理
# ----------------------------------------------------------

@mcp.tool()
def add_memory(
    tenant_id: str,
    project_id: str,
    user_id: str,
    content: str,
    memory_type: str = "factual",
    tags: str = "",
    importance: float = 0.0,
) -> str:
    """
    存储一条用户记忆。

    当你在对话中了解到用户的重要信息时，调用此工具将其存储。

    Args:
        tenant_id: 租户 ID
        project_id: 项目 ID
        user_id: 用户唯一标识
        content: 记忆内容（如 "用户喜欢安静的环境"）
        memory_type: 记忆类型，可选值: factual(事实) / preference(偏好) / episodic(经历) / session(会话)
        tags: 标签，多个用逗号分隔（如 "饮食,偏好"）
        importance: 重要度 0.0-1.0，越高越重要
    """
    try:
        mt = MemoryType(memory_type)
    except ValueError:
        return f"错误：无效的记忆类型 '{memory_type}'，可选: factual, preference, episodic, session"

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    fragment = _memory_manager.add(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        content=content,
        memory_type=mt,
        tags=tag_list,
        importance=importance,
    )

    logger.info("MCP: 添加记忆 id=%s, user=%s", fragment.id, user_id)
    return json.dumps({
        "status": "success",
        "id": fragment.id,
        "content": fragment.content,
        "memory_type": fragment.memory_type.value,
    }, ensure_ascii=False)


@mcp.tool()
def search_memory(
    tenant_id: str,
    project_id: str,
    user_id: str,
    query: str,
    limit: int = 5,
    memory_type: str = "",
) -> str:
    """
    语义搜索用户记忆。

    当你需要回忆关于用户的信息时，调用此工具进行语义搜索。

    Args:
        tenant_id: 租户 ID
        project_id: 项目 ID
        user_id: 用户唯一标识
        query: 搜索查询（如 "用户的饮食偏好"）
        limit: 返回结果数量上限（默认 5）
        memory_type: 按类型过滤，留空则搜索所有类型
    """
    mt = None
    if memory_type:
        try:
            mt = MemoryType(memory_type)
        except ValueError:
            return f"错误：无效的记忆类型 '{memory_type}'"

    results = _memory_manager.search(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        query=query,
        limit=limit,
        memory_type=mt,
    )

    logger.info("MCP: 搜索记忆 user=%s, query='%s', 结果=%d", user_id, query[:30], len(results))

    if not results:
        return "未找到相关记忆。"

    output = []
    for r in results:
        output.append({
            "content": r["content"],
            "type": r["memory_type"],
            "tags": r.get("tags", []),
            "importance": r.get("importance", 0.0),
            "score": round(r.get("score", 0.0), 3),
            "created_at": r.get("created_at", ""),
        })

    return json.dumps(output, ensure_ascii=False, indent=2)


@mcp.tool()
def add_message(
    tenant_id: str,
    project_id: str,
    user_id: str,
    content: str,
    role: str,
    session_id: str,
) -> str:
    """
    存储一条会话消息。

    用于保存对话上下文，方便后续检索历史会话。

    Args:
        tenant_id: 租户 ID
        project_id: 项目 ID
        user_id: 用户唯一标识
        content: 消息内容
        role: 消息角色：user / assistant / system
        session_id: 会话 ID
    """
    try:
        r = Role(role)
    except ValueError:
        return f"错误：无效的角色 '{role}'，可选: user, assistant, system"

    fragment = _memory_manager.add_message(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        content=content,
        role=r,
        session_id=session_id,
    )

    return json.dumps({
        "status": "success",
        "id": fragment.id,
        "session_id": session_id,
    }, ensure_ascii=False)


@mcp.tool()
def get_history(
    tenant_id: str,
    project_id: str,
    user_id: str,
    session_id: str,
    limit: int = 50,
) -> str:
    """
    获取会话历史消息。

    Args:
        tenant_id: 租户 ID
        project_id: 项目 ID
        user_id: 用户唯一标识
        session_id: 会话 ID
        limit: 返回数量上限
    """
    results = _memory_manager.get_history(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        session_id=session_id,
        limit=limit,
    )

    if not results:
        return "该会话暂无历史消息。"

    messages = [
        {"role": r.get("role", "user"), "content": r["content"]}
        for r in results
    ]

    return json.dumps(messages, ensure_ascii=False, indent=2)


@mcp.tool()
def delete_memory(
    tenant_id: str,
    project_id: str,
    user_id: str,
    memory_id: str,
) -> str:
    """
    删除一条记忆。

    Args:
        tenant_id: 租户 ID
        project_id: 项目 ID
        user_id: 用户唯一标识
        memory_id: 要删除的记忆 ID
    """
    success = _memory_manager.delete(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        fragment_id=memory_id,
    )

    if success:
        logger.info("MCP: 删除记忆 id=%s", memory_id)
        return json.dumps({"status": "success", "deleted_id": memory_id}, ensure_ascii=False)
    else:
        return json.dumps({"status": "error", "detail": "记忆不存在或无权删除"}, ensure_ascii=False)


@mcp.tool()
def get_user_stats(
    tenant_id: str,
    project_id: str,
    user_id: str,
) -> str:
    """
    获取用户记忆统计信息。

    Args:
        tenant_id: 租户 ID
        project_id: 项目 ID
        user_id: 用户唯一标识
    """
    stats = _memory_manager.get_stats(
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
    )

    return json.dumps({
        "user_id": user_id,
        "total_memories": stats["total"],
        "by_type": stats["by_type"],
    }, ensure_ascii=False, indent=2)


# ----------------------------------------------------------
# 入口
# ----------------------------------------------------------

def main():
    """启动 Engrama MCP Server"""
    parser = argparse.ArgumentParser(description="Engrama MCP Server")
    parser.add_argument(
        "--transport", choices=["stdio", "sse"], default="stdio",
        help="传输方式：stdio（默认，供 Claude Desktop/Cursor 使用）或 sse（HTTP 远程访问）",
    )
    parser.add_argument(
        "--port", type=int, default=8001,
        help="SSE 模式的端口号（默认 8001）",
    )
    args = parser.parse_args()

    logger.info("启动 Engrama MCP Server (transport=%s)", args.transport)

    if args.transport == "sse":
        mcp.run(transport="sse", sse_params={"port": args.port})
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
