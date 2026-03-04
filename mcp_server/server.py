"""
Engrama MCP Server

将 Engrama 的记忆管理能力通过 MCP (Model Context Protocol) 暴露给 AI 模型。
AI 模型（如 Claude、Cursor 等）可以通过 MCP 协议直接调用 Engrama 的记忆功能，
自主决定何时存取用户记忆。

鉴权机制：
    MCP Server 启动时必须提供 API Key（环境变量或 CLI 参数），
    通过 MetaStore 验证 Key 并绑定 tenant_id / project_id / user_id。
    所有 Tool 自动使用绑定的身份上下文，AI 模型无需感知底层主键。

    API Key 分级：
    - 项目级 Key（B 端）：user_id 需由 AI 或 ENGRAMA_USER_ID 环境变量提供
    - 用户级 Key（C 端）：user_id 自动从 Key 绑定，AI 无需关心

使用方式：
    # stdio 模式（Claude Desktop / Cursor 等 MCP 客户端）
    ENGRAMA_API_KEY=eng_xxxx python -m mcp_server

    # 用户级 Key + 默认用户
    ENGRAMA_API_KEY=eng_xxxx ENGRAMA_USER_ID=nil python -m mcp_server

    # 或者通过 CLI 参数
    python -m mcp_server --api-key eng_xxxx

    # SSE 模式（HTTP 远程访问）
    ENGRAMA_API_KEY=eng_xxxx python -m mcp_server --transport sse --port 8001
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Optional

from mcp.server.fastmcp import FastMCP

from engrama.logger import get_logger
from engrama.models import MemoryType, Role
from engrama.store.qdrant_store import QdrantStore
from engrama.store.base_meta_store import BaseMetaStore
from engrama.store import create_meta_store
from engrama.memory_manager import MemoryManager

logger = get_logger(__name__)


# ----------------------------------------------------------
# 鉴权上下文
# ----------------------------------------------------------

@dataclass
class AuthContext:
    """MCP 鉴权上下文，存储从 API Key 解析出的身份信息"""
    tenant_id: str
    project_id: str
    api_key: str
    user_id: Optional[str] = None           # 从 Key 绑定（用户级 Key）
    default_user_id: Optional[str] = None   # 从 ENGRAMA_USER_ID 环境变量


# 全局上下文（stdio 模式为单客户端，全局即可）
_auth: Optional[AuthContext] = None


def _resolve_user_id(passed_user_id: str = "") -> str:
    """
    解析最终使用的 user_id

    优先级：
    1. API Key 绑定的 user_id（最高，不可覆盖）
    2. 调用方显式传入的 user_id
    3. ENGRAMA_USER_ID 环境变量
    4. 报错

    Args:
        passed_user_id: Tool 调用时传入的 user_id

    Returns:
        解析后的 user_id

    Raises:
        ValueError: 无法确定 user_id
    """
    # 1. Key 绑定（最高优先级）
    if _auth.user_id:
        if passed_user_id and passed_user_id != _auth.user_id:
            raise ValueError(
                f"此 API Key 已绑定用户 '{_auth.user_id}'，不允许操作其他用户数据。请不要传入 user_id 参数。"
            )
        return _auth.user_id

    # 2. 调用方传入
    if passed_user_id:
        return passed_user_id

    # 3. 环境变量默认值
    if _auth.default_user_id:
        return _auth.default_user_id

    # 4. 无法确定
    raise ValueError(
        "缺少 user_id。请在调用时传入 user_id，"
        "或通过 ENGRAMA_USER_ID 环境变量设置默认值，"
        "或使用用户级 API Key（生成 Key 时绑定 user_id）。"
    )


def verify_and_bind(api_key: str, meta_store: BaseMetaStore) -> AuthContext:
    """
    验证 API Key 并绑定身份上下文

    Args:
        api_key: 待验证的 API Key
        meta_store: 元数据存储实例

    Returns:
        AuthContext: 验证通过的身份上下文

    Raises:
        SystemExit: 验证失败时退出进程
    """
    if not api_key:
        logger.error("❌ 缺少 API Key。请通过 ENGRAMA_API_KEY 环境变量或 --api-key 参数提供。")
        sys.exit(1)

    result = meta_store.verify_api_key(api_key)
    if result is None:
        logger.error("❌ 无效的 API Key: %s", api_key[:10] + "...")
        sys.exit(1)

    default_user_id = os.environ.get("ENGRAMA_USER_ID", "")

    ctx = AuthContext(
        tenant_id=result.tenant_id,
        project_id=result.project_id,
        api_key=api_key,
        user_id=result.user_id,
        default_user_id=default_user_id or None,
    )

    key_type = "用户级" if ctx.user_id else "项目级"
    logger.info(
        "MCP 鉴权成功 (%s Key): tenant=%s, project=%s%s%s",
        key_type, ctx.tenant_id, ctx.project_id,
        f", user={ctx.user_id}" if ctx.user_id else "",
        f", default_user={ctx.default_user_id}" if ctx.default_user_id else "",
    )
    return ctx


# ----------------------------------------------------------
# 初始化 MCP Server（延迟到 main() 中鉴权后）
# ----------------------------------------------------------

mcp = FastMCP(
    "engrama",
    instructions=(
        "You are connected to Engrama, an intelligent Agentic Memory layer designed to provide personalized, long-term memory capabilities.\n"
        "This system acts as your episodic and preference memory, allowing you to build continuity across interactions.\n\n"
        "【Core Responsibilities】\n"
        "1. PROACTIVE EXTRACTION (add_memory): When the user explicitly or implicitly shares personal preferences, facts, workflow habits, or corrections, you should call `add_memory` to store them. This ensures you 'learn' about the user over time.\n"
        "2. CONTEXTUAL RETRIEVAL (search_memory): If a user's request requires historical context, leans on personal preferences, or refers to past interactions (e.g., 'Do it like we did last time'), call `search_memory` to fetch the relevant context before answering.\n"
        "3. NATURAL INTEGRATION: Use retrieved memories seamlessly as if you naturally remembered them. Avoid robotic phrasing like 'According to my database'.\n\n"
        "【Strict Boundary Definitions (DO NOT VIOLATE)】\n"
        "- ❌ NOT FOR GENERAL KNOWLEDGE: Engrama is for USER-SPECIFIC context. Do NOT use it to search for general coding syntax, public API documentation, or broad factual knowledge. Use dedicated RAG tools, code search, or web search for those purposes.\n"
        "- ❌ AVOID TOOL CONFUSION: If the user asks you to read a codebase, analyze a framework, or write a standard script from documentation, prioritize Code RAG or filesystem tools over Engrama."
    ),
)

# 业务层实例（全局单例）
_vector_store: Optional[QdrantStore] = None
_meta_store: Optional[BaseMetaStore] = None
_memory_manager: Optional[MemoryManager] = None


def _init_services():
    """初始化业务层服务"""
    global _vector_store, _meta_store, _memory_manager
    _meta_store = create_meta_store()
    _vector_store = QdrantStore(meta_store=_meta_store)
    _memory_manager = MemoryManager(vector_store=_vector_store, meta_store=_meta_store)
    logger.info("Engrama 业务层初始化完成")


# ----------------------------------------------------------
# MCP Tools — 记忆管理（user_id 可选，自动解析）
# ----------------------------------------------------------

@mcp.tool()
def add_memory(
    content: str,
    user_id: str = "",
    memory_type: str = "factual",
    tags: str = "",
    importance: float = 0.0,
) -> str:
    """
    存储一条用户记忆。

    当你在对话中了解到用户的重要信息时，调用此工具将其存储。

    Args:
        content: 记忆内容（如 "用户喜欢安静的环境"）
        user_id: 用户标识（如已通过 API Key 或环境变量绑定，则可不填）
        memory_type: 记忆类型，可选值: factual(事实) / preference(偏好) / episodic(经历) / session(会话)
        tags: 标签，多个用逗号分隔（如 "饮食,偏好"）
        importance: 重要度 0.0-1.0，越高越重要
    """
    try:
        resolved_uid = _resolve_user_id(user_id)
    except ValueError as e:
        return str(e)

    try:
        mt = MemoryType(memory_type)
    except ValueError:
        return f"错误：无效的记忆类型 '{memory_type}'，可选: factual, preference, episodic, session"

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    fragment = _memory_manager.add(
        tenant_id=_auth.tenant_id,
        project_id=_auth.project_id,
        user_id=resolved_uid,
        content=content,
        memory_type=mt,
        tags=tag_list,
        importance=importance,
    )

    logger.info("MCP: 添加记忆 id=%s, user=%s", fragment.id, resolved_uid)
    return json.dumps({
        "status": "success",
        "id": fragment.id,
        "content": fragment.content,
        "memory_type": fragment.memory_type.value,
    }, ensure_ascii=False)


@mcp.tool()
def search_memory(
    query: str,
    user_id: str = "",
    limit: int = 5,
    memory_type: str = "",
) -> str:
    """
    语义搜索用户记忆。

    当你需要回忆关于用户的信息时，调用此工具进行语义搜索。

    Args:
        query: 搜索查询（如 "用户的饮食偏好"）
        user_id: 用户标识（如已通过 API Key 或环境变量绑定，则可不填）
        limit: 返回结果数量上限（默认 5）
        memory_type: 按类型过滤，留空则搜索所有类型
    """
    try:
        resolved_uid = _resolve_user_id(user_id)
    except ValueError as e:
        return str(e)

    mt = None
    if memory_type:
        try:
            mt = MemoryType(memory_type)
        except ValueError:
            return f"错误：无效的记忆类型 '{memory_type}'"

    results = _memory_manager.search(
        tenant_id=_auth.tenant_id,
        project_id=_auth.project_id,
        user_id=resolved_uid,
        query=query,
        limit=limit,
        memory_type=mt,
    )

    logger.info("MCP: 搜索记忆 user=%s, query='%s', 结果=%d", resolved_uid, query[:30], len(results))

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
    content: str,
    role: str,
    session_id: str,
    user_id: str = "",
) -> str:
    """
    存储一条会话消息。

    用于保存对话上下文，方便后续检索历史会话。

    Args:
        content: 消息内容
        role: 消息角色：user / assistant / system
        session_id: 会话 ID
        user_id: 用户标识（如已通过 API Key 或环境变量绑定，则可不填）
    """
    try:
        resolved_uid = _resolve_user_id(user_id)
    except ValueError as e:
        return str(e)

    try:
        r = Role(role)
    except ValueError:
        return f"错误：无效的角色 '{role}'，可选: user, assistant, system"

    fragment = _memory_manager.add_message(
        tenant_id=_auth.tenant_id,
        project_id=_auth.project_id,
        user_id=resolved_uid,
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
    session_id: str,
    user_id: str = "",
    limit: int = 50,
) -> str:
    """
    获取会话历史消息。

    Args:
        session_id: 会话 ID
        user_id: 用户标识（如已通过 API Key 或环境变量绑定，则可不填）
        limit: 返回数量上限
    """
    try:
        resolved_uid = _resolve_user_id(user_id)
    except ValueError as e:
        return str(e)

    results = _memory_manager.get_history(
        tenant_id=_auth.tenant_id,
        project_id=_auth.project_id,
        user_id=resolved_uid,
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
    memory_id: str,
    user_id: str = "",
) -> str:
    """
    删除一条记忆。

    Args:
        memory_id: 要删除的记忆 ID
        user_id: 用户标识（如已通过 API Key 或环境变量绑定，则可不填）
    """
    try:
        resolved_uid = _resolve_user_id(user_id)
    except ValueError as e:
        return str(e)

    success = _memory_manager.delete(
        tenant_id=_auth.tenant_id,
        project_id=_auth.project_id,
        user_id=resolved_uid,
        fragment_id=memory_id,
    )

    if success:
        logger.info("MCP: 删除记忆 id=%s", memory_id)
        return json.dumps({"status": "success", "deleted_id": memory_id}, ensure_ascii=False)
    else:
        return json.dumps({"status": "error", "detail": "记忆不存在或无权删除"}, ensure_ascii=False)


@mcp.tool()
def get_user_stats(
    user_id: str = "",
) -> str:
    """
    获取用户记忆统计信息。

    Args:
        user_id: 用户标识（如已通过 API Key 或环境变量绑定，则可不填）
    """
    try:
        resolved_uid = _resolve_user_id(user_id)
    except ValueError as e:
        return str(e)

    stats = _memory_manager.get_stats(
        tenant_id=_auth.tenant_id,
        project_id=_auth.project_id,
        user_id=resolved_uid,
    )

    return json.dumps({
        "user_id": resolved_uid,
        "total_memories": stats["total"],
        "by_type": stats["by_type"],
    }, ensure_ascii=False, indent=2)


# ----------------------------------------------------------
# 入口
# ----------------------------------------------------------

def main():
    """启动 Engrama MCP Server"""
    global _auth

    parser = argparse.ArgumentParser(description="Engrama MCP Server")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ENGRAMA_API_KEY", ""),
        help="API Key（也可通过 ENGRAMA_API_KEY 环境变量设置）",
    )
    parser.add_argument(
        "--transport", choices=["stdio", "sse"], default="stdio",
        help="传输方式：stdio（默认）或 sse（HTTP 远程）",
    )
    parser.add_argument(
        "--port", type=int, default=8001,
        help="SSE 模式的端口号（默认 8001）",
    )
    args = parser.parse_args()

    # 1. 初始化业务层
    _init_services()

    # 2. 鉴权：验证 API Key 并绑定身份上下文
    _auth = verify_and_bind(args.api_key, _meta_store)

    # 3. 启动 MCP Server
    logger.info("启动 Engrama MCP Server (transport=%s)", args.transport)

    if args.transport == "sse":
        mcp.run(transport="sse", sse_params={"port": args.port})
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
