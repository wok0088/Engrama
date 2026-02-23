<p align="center">
  <h1 align="center">🧠 Engrama</h1>
  <p align="center"><strong>通用 AI 记忆中间件（Memory-as-a-Service）</strong></p>
  <p align="center">为各类 AI 项目提供「按渠道接入、按用户隔离」的记忆存储与语义检索服务</p>
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="#核心功能">核心功能</a> ·
  <a href="#api-文档">API 文档</a> ·
  <a href="#mcp-server">MCP Server</a> ·
  <a href="#架构设计">架构设计</a>
</p>

---

## ✨ 什么是 Engrama

Engrama 是一个**轻量级、通用的 AI 记忆中间件**，解决 AI 项目中的一个核心痛点：**如何让 AI 记住用户**。

- 🔌 **即插即用** — 3 行代码接入，REST API 设计
- 💰 **零 LLM 成本** — 基础功能不依赖任何大模型
- 🔒 **三层隔离** — Tenant → Project → User，数据天然隔离
- 🔍 **语义搜索** — 不只是关键词匹配，理解语义的记忆检索
- 📦 **自部署** — 完全私有化部署，数据掌握在自己手中

## 📌 版本信息

| 版本 | 状态 | 说明 |
|---|---|---|
| **v0.3.0** | ✅ 当前版本 | 生产化加固 + MCP Server |
| v1.0.0 | 🔮 规划中 | 记忆智能化（摘要、冲突检测、淘汰策略） |
| v2.0.0 | 🔮 规划中 | 平台化（Web UI、SDK） |

> **版本策略**：遵循 [Semantic Versioning](https://semver.org/)。`0.x.y` 阶段 API 可能有变更，`1.0.0` 起 API 稳定。

## 🚀 快速开始

### 环境要求

- **Python** 3.11 — 3.13（⚠️ 暂不支持 3.14，ChromaDB 兼容性问题）
- **pip**

### 安装

```bash
git clone https://github.com/wok0088/cortex.git
cd cortex

# 创建虚拟环境
python3.12 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 启动服务

```bash
uvicorn api.main:app --reload
# 🎉 访问 http://localhost:8000/docs 查看交互式 API 文档
```

### 30 秒上手

```bash
# 1️⃣ 注册租户
curl -X POST http://localhost:8000/v1/channels/tenants \
  -H "Content-Type: application/json" \
  -d '{"name": "我的公司"}'
# 返回: {"id": "TENANT_ID", ...}

# 2️⃣ 创建项目
curl -X POST http://localhost:8000/v1/channels/projects \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "TENANT_ID", "name": "AI 助手"}'
# 返回: {"id": "PROJECT_ID", ...}

# 3️⃣ 生成 API Key
curl -X POST http://localhost:8000/v1/channels/api-keys \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "TENANT_ID", "project_id": "PROJECT_ID"}'
# 返回: {"key": "ctx_xxxx", ...}

# 4️⃣ 存入记忆
curl -X POST http://localhost:8000/v1/memories \
  -H "X-API-Key: ctx_xxxx" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user_001", "content": "喜欢安静的环境", "memory_type": "preference"}'

# 5️⃣ 语义搜索
curl -X POST http://localhost:8000/v1/memories/search \
  -H "X-API-Key: ctx_xxxx" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user_001", "query": "用户的偏好是什么"}'
```

## 🧩 核心功能

### 四种记忆类型

| 类型 | 标识 | 说明 | 示例 |
|---|---|---|---|
| 事实记忆 | `factual` | 客观事实信息 | "生日是 1990-03-15" |
| 偏好记忆 | `preference` | 主观偏好 | "喜欢安静的环境" |
| 经历记忆 | `episodic` | 具体交互事件 | "2025-01-15 咨询过八字" |
| 会话记忆 | `session` | 对话上下文消息 | 一轮完整的对话 |

### 三层租户隔离

```
Tenant（租户：企业 / 个人开发者）
  └── Project（项目：酒店 AI / 客服 AI）
       └── User（用户：张三 / 李四）
            └── Memory Fragment（记忆片段）
```

### 智能预留字段

每条记忆预留 `hit_count`（检索命中次数）和 `importance`（重要度评分），为未来的检索优化和智能淘汰做数据准备。

## 📡 API 文档

启动服务后访问 `/docs` 查看完整的交互式 API 文档（Swagger UI）。

### 记忆管理（需要 API Key 认证）

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/v1/memories` | 添加记忆 |
| `POST` | `/v1/memories/search` | 语义搜索 |
| `GET` | `/v1/memories?user_id=xxx` | 列出记忆 |
| `DELETE` | `/v1/memories/{id}?user_id=xxx` | 删除记忆 |
| `GET` | `/v1/sessions/{id}/history?user_id=xxx` | 会话历史 |
| `GET` | `/v1/users/{id}/stats` | 统计信息 |

### 渠道管理（需要管理员 Token）

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/v1/channels/tenants` | 注册租户 |
| `GET` | `/v1/channels/tenants` | 列出租户 |
| `POST` | `/v1/channels/projects` | 创建项目 |
| `POST` | `/v1/channels/api-keys` | 生成 API Key |

### 认证方式

记忆管理 API 需要在请求头中携带 API Key：

```
X-API-Key: ctx_xxxxxxxxxxxx
```

API Key 会自动关联到对应的 Tenant 和 Project，无需在每次请求中重复指定。

渠道管理 API 在生产环境需要管理员 Token：

```
X-Admin-Token: your_secret_token
```

## 🤖 MCP Server

Engrama 提供 MCP (Model Context Protocol) 接口，让 AI 模型可以**直接调用**记忆功能。

### 两种接入方式对比

| | HTTP REST API | MCP Server |
|---|---|---|
| **调用方** | 你的后端代码 | AI 模型自主调用 |
| **集成方式** | httpx / requests | Claude Desktop、Cursor 等 |
| **灵活性** | 你完全控制调用逻辑 | AI 自行判断何时查/存 |
| **适用场景** | 生产环境、自定义应用 | AI 原生应用、IDE 集成 |

### MCP 提供的 Tools

| Tool | 说明 |
|---|---|
| `add_memory` | 存储用户记忆（事实/偏好/经历） |
| `search_memory` | 语义搜索用户记忆 |
| `add_message` | 存储会话消息 |
| `get_history` | 获取会话历史 |
| `delete_memory` | 删除记忆 |
| `get_user_stats` | 获取用户记忆统计 |

### 启动 MCP Server

```bash
# stdio 模式（供 Claude Desktop / Cursor 使用）
python -m mcp_server

# SSE 模式（HTTP 远程访问）
python -m mcp_server --transport sse --port 8001
```

### 配置 Claude Desktop

在 `claude_desktop_config.json` 中添加：

```json
{
  "mcpServers": {
    "cortex": {
      "command": "/path/to/cortex/.venv/bin/python",
      "args": ["-m", "mcp_server"],
      "cwd": "/path/to/cortex"
    }
  }
}
```

### 配置 Cursor

在项目根目录创建 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "cortex": {
      "command": "/path/to/cortex/.venv/bin/python",
      "args": ["-m", "mcp_server"],
      "cwd": "/path/to/cortex"
    }
  }
}
```

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────┐
│  接入层                                              │
│  ┌─────────────────────┐ ┌─────────────────────────┐│
│  │ REST API (FastAPI)  │ │ MCP Server (FastMCP)    ││
│  │ HTTP · 认证中间件   │ │ stdio · SSE             ││
│  └─────────┬───────────┘ └────────────┬────────────┘│
├────────────┴──────────────────────────┴─────────────┤
│              业务层                                   │
│    MemoryManager · ChannelManager                    │
├──────────────────┬──────────────────────────────────┤
│  VectorStore     │     MetaStore                     │
│  (ChromaDB)      │     (SQLite)                      │
│  语义搜索        │     租户/项目/Key 管理             │
└──────────────────┴──────────────────────────────────┘
```

### 项目结构

```
cortex/
├── cortex/                  # 核心包
│   ├── config.py            # 配置管理
│   ├── models.py            # 数据模型（Pydantic v2）
│   ├── logger.py            # 统一日志
│   ├── memory_manager.py    # 记忆管理核心 API
│   ├── channel_manager.py   # 渠道管理
│   └── store/
│       ├── vector_store.py  # ChromaDB 向量存储
│       └── meta_store.py    # SQLite 元数据存储
├── api/                     # REST API 层
│   ├── main.py              # FastAPI 入口
│   ├── middleware.py        # API Key + Admin Token 认证
│   ├── rate_limiter.py      # 速率限制
│   └── routes/
│       ├── memories.py      # 记忆路由
│       └── channels.py      # 渠道路由
├── mcp_server/              # MCP Server
│   ├── server.py            # MCP Tools 定义
│   └── __main__.py          # 入口
├── tests/                   # 测试（47 个）
├── Dockerfile               # Docker 镜像构建
├── docker-compose.yml       # Docker Compose 编排
├── data/                    # 运行时数据（自动生成）
└── requirements.txt
```

### 技术栈

| 组件 | 技术 | 说明 |
|---|---|---|
| 语言 | Python 3.11+ | 核心语言 |
| Web 框架 | FastAPI | 高性能 API |
| MCP | mcp (FastMCP) | AI 模型直接调用 |
| 向量数据库 | ChromaDB | 语义搜索引擎 |
| Embedding | BAAI/bge-small-zh-v1.5 | 中文语义模型 |
| 元数据存储 | SQLite | 轻量级关系型存储 |
| 数据验证 | Pydantic v2 | 类型安全的数据模型 |
| 测试 | pytest | 单元测试 + 集成测试 |

## 🧪 测试

```bash
# 运行全部测试
python -m pytest tests/ -v

# 运行特定层的测试
python -m pytest tests/test_store.py -v    # 存储层
python -m pytest tests/test_memory.py -v   # 业务层
python -m pytest tests/test_channel.py -v  # 渠道管理
python -m pytest tests/test_api.py -v      # API 集成
```

## ⚙️ 配置

通过环境变量自定义配置：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `CORTEX_DATA_DIR` | `./data` | 数据持久化目录 |
| `CORTEX_ADMIN_TOKEN` | `""` (免认证) | 渠道管理 API 管理员 Token |
| `CORTEX_EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | Embedding 模型 |
| `CORTEX_CORS_ORIGINS` | `*` | CORS 允许的域名 |
| `CORTEX_RATE_LIMIT` | `0` (不限制) | 每分钟最大请求数 |
| `CORTEX_LOG_LEVEL` | `INFO` | 日志级别 |

## 🐳 Docker 部署

```bash
# 一键启动
docker-compose up --build

# 生产环境（设置管理员 Token）
CORTEX_ADMIN_TOKEN=your_secret docker-compose up --build -d
```

## 📄 License

MIT License

## 🤝 Contributing

欢迎提交 Issue 和 Pull Request！
