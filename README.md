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
| **v0.4.3** | ✅ 当前版本 | 外键约束生效 + 速率限制修复 + 测试基础设施优化 |
| v0.4.2 | 🔖 历史版本 | Code Review 修复加固 + 全面测试覆盖 |
| v0.4.0 | 🔖 历史版本 | 生产化加固 + MCP Server (鉴权) |
| v1.0.0 | 🔮 规划中 | 记忆智能化（摘要、冲突检测、淘汰策略） |
| v2.0.0 | 🔮 规划中 | 平台化（Web UI、SDK） |

> **版本策略**：遵循 [Semantic Versioning](https://semver.org/)。`0.x.y` 阶段 API 可能有变更，`1.0.0` 起 API 稳定。

## 🚀 快速开始

### 环境要求

- **Python** 3.11 — 3.13（⚠️ 暂不支持 3.14，ChromaDB 兼容性问题）
- **pip**

### 安装

```bash
git clone https://github.com/wok0088/engrama.git
cd engrama

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
# 返回: {"key": "eng_xxxx", ...}

# 4️⃣ 存入记忆（项目级 Key需传 user_id，用户级 Key可省略）
curl -X POST http://localhost:8000/v1/memories \
  -H "X-API-Key: eng_xxxx" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user_001", "content": "喜欢安静的环境", "memory_type": "preference"}'

# 5️⃣ 语义搜索
curl -X POST http://localhost:8000/v1/memories/search \
  -H "X-API-Key: eng_xxxx" \
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
| `GET` | `/v1/users/me/stats` | 获取当前绑定用户的统计 (无需 user_id) |
| `GET` | `/v1/users/{id}/stats` | 获取指定用户的统计信息 |

### 渠道管理（需要管理员 Token）

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/v1/channels/tenants` | 注册租户 |
| `GET` | `/v1/channels/tenants` | 列出租户 |
| `POST` | `/v1/channels/projects` | 创建项目 |
| `POST` | `/v1/channels/api-keys` | 生成 API Key (支持绑定特定的 user_id) |

### 认证方式

记忆管理 API 需要在请求头中携带 API Key：

```
X-API-Key: eng_xxxxxxxxxxxx
```

API Key 会自动关联到对应的 Tenant 和 Project，无需在每次请求中重复指定。

**💡 API Key 分级策略：**
*   **项目级 Key（B端场景）**：生成时不指定 `user_id`。API 调用方必须在请求体或 Query 参数中显式传入被操作的 `user_id`，以支持全局用户管理。
*   **用户级 Key（C端场景）**：生成时直接绑定具体的 `user_id`。持有该 Key 的客户端或 AI 实体可以**完全省略所有的 `user_id` 请求参数**，引擎会自动赋予该绑定分身的身份。若被伪造跨域调用将直接遭遇 `403` 阻断。

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

MCP Server 启动时必须提供 API Key（与 HTTP API 使用同一套 Key）：

```bash
# stdio 模式（客户端 C 端集成，利用用户级 API Key 自动绑定 user_id）
ENGRAMA_API_KEY=eng_xxxx python -m mcp_server

# stdio 模式（B端平台调用，携带项目级 Key 通过环境变量指认默认用户）
ENGRAMA_API_KEY=eng_xxxx ENGRAMA_USER_ID=user_001 python -m mcp_server

# 或者通过 CLI 参数
python -m mcp_server --api-key eng_xxxx

# SSE 模式（HTTP 远程访问）
ENGRAMA_API_KEY=eng_xxxx python -m mcp_server --transport sse --port 8001
```

### 配置 Claude Desktop

在 `claude_desktop_config.json` 中添加：

```json
{
  "mcpServers": {
    "engrama": {
      "command": "/path/to/engrama/.venv/bin/python",
      "args": ["-m", "mcp_server"],
      "cwd": "/path/to/engrama",
      "env": {
        "ENGRAMA_API_KEY": "eng_xxxx"
      }
    }
  }
}
```

### 配置 Cursor

在项目根目录创建 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "engrama": {
      "command": "/path/to/engrama/.venv/bin/python",
      "args": ["-m", "mcp_server"],
      "cwd": "/path/to/engrama",
      "env": {
        "ENGRAMA_API_KEY": "eng_xxxx"
      }
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
engrama/
├── engrama/                  # 核心包
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
├── tests/                   # 测试（89 个，涵盖鉴权和隔离边界测试）
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
| Embedding | BAAI/bge-m3 | 本地多语言语义模型 |
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
| `ENGRAMA_DATA_DIR` | `./data` | 数据持久化目录 |
| `ENGRAMA_ADMIN_TOKEN` | `""` (免认证) | 渠道管理 API 管理员 Token |
| `ENGRAMA_EMBEDDING_MODEL` | `BAAI/bge-m3` | Embedding 模型 |
| `ENGRAMA_CORS_ORIGINS` | `*` | CORS 允许的域名 |
| `ENGRAMA_RATE_LIMIT` | `0` (不限制) | 每分钟最大请求数 |
| `ENGRAMA_LOG_LEVEL` | `INFO` | 日志级别 |

## 🐳 Docker 部署

```bash
# 一键启动
docker-compose up --build

# 生产环境（设置管理员 Token）
ENGRAMA_ADMIN_TOKEN=your_secret docker-compose up --build -d
```

## 📄 License

MIT License

## 🤝 Contributing

欢迎提交 Issue 和 Pull Request！
