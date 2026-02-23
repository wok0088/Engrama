# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/) 版本规范。

## [0.4.1] - 2026-02-23

### 🐛 缺陷修复
- **接口分离** — 针对用户级 Key 新增 `GET /v1/users/me/stats` 路由，消除了查询统计信息时强制传入 URL 路径参数的矛盾。
- **越权防御** — 在生成 API Key 时，添加了严密的租户权限校验，杜绝了跨租户绑定 Project 的安全漏洞。
- **状态不一致修复** — 纠正了删除项目时的 API Key 物理删除逻辑，现在全部统一为主键下沉的软删除 (`is_active=0`)。
- **并发性能安全** — 修改了 HTTP 请求鉴权中间件在拦截 API 时对 SQLite 的同步调用，采用线程池委派防止阻塞事件循环。
- **MCP 容错与规范** — 为鉴权解包增加空指针防护，并统一下放所有拦截级与应用级的错误日志封装为严格的 JSON 形式 (`{"error": "..."}`)。

## [0.4.0] - 2026-02-23

### 🔒 安全加固
- **MCP Server 鉴权** — 启动时必须提供 API Key（`ENGRAMA_API_KEY` 环境变量或 `--api-key` 参数）
- **Tool 参数降维** — 从 Tool 签名中移除 `tenant_id`/`project_id`，AI 模型无需感知系统主键，避免 IDOR 越权漏洞
- **身份注入** — API Key 验证后自动绑定 tenant/project 上下文，与 HTTP API 使用同一套鉴权体系
- **API Key 分级** — 支持项目级 Key（B 端，调用方传 user_id）和用户级 Key（C 端，user_id 自动绑定不可覆盖）
- **`ENGRAMA_USER_ID`** — MCP 场景支持通过环境变量设置默认用户 ID
- **越权防护** — 用户级 Key 传入不匹配的 user_id 时返回 403

### 🔍 改进
- **Embedding 模型** — 默认切换为 `BAAI/bge-m3`（多语言模型，向量维度 1024），模型文件存放在项目 `data/models/` 目录下

### 🐛 关键修复
- **鉴权越权防范** — MCP/HTTP 在遇到用户级 Key 被非法跨域使用（传入不匹配的 user_id）时一致返回 403 / ValueError 拒绝访问，而不是静默覆盖
- **可选请求字段** — HTTP Add/Search/Update 记忆路由的 `user_id` 改为 `Optional`，对 C 端用户级 Key 实现无感知调用
- **数据响应修正** — 修复了 `get_user_stats` 返回原始传入 `user_id` 而非运行时解析 `user_id` 的绑定偏差 bug
- **代码重构** — 移除了 MetaStore 与 ChannelManager 的冗余日志及服务器代码中的僵尸引用

## [0.3.0] - 2026-02-23

### ✨ 新功能
- **MCP Server** — 通过 MCP (Model Context Protocol) 协议让 AI 模型直接调用 Engrama 记忆功能
  - 6 个 MCP Tools：`add_memory`、`search_memory`、`add_message`、`get_history`、`delete_memory`、`get_user_stats`
  - 支持 stdio 和 SSE 两种传输方式
  - 可接入 Claude Desktop、Cursor 等 MCP 客户端

### 📦 依赖
- 新增 `mcp` (官方 MCP Python SDK)

## [0.2.1] - 2026-02-23

### 🐛 关键修复
- **修复事件循环阻塞** — 所有路由函数从 `async def` 改为 `def`，FastAPI 自动将阻塞操作（Embedding 计算、ChromaDB 查询）放入线程池执行，并发能力从 1 恢复正常
- **优化 Collection 粒度** — 从 per-user（`{tenant}__{project}__{user}`）改为 per-project（`{tenant}__{project}`），用户隔离通过 metadata `where` 过滤实现，解决海量用户下 Collection 膨胀问题

## [0.2.0] - 2026-02-22

### 🔒 安全加固
- **渠道管理 API 认证** — 新增 `X-Admin-Token` 管理员认证，生产环境通过 `CORTEX_ADMIN_TOKEN` 环境变量配置
- **输入长度限制** — content（10000 字符）、name（100 字符）、tags（20 个）等关键字段增加校验
- **速率限制** — 基于内存的滑动窗口限制，通过 `CORTEX_RATE_LIMIT` 环境变量配置每分钟最大请求数

### ✨ 新功能
- **中文语义搜索** — 默认使用 `BAAI/bge-small-zh-v1.5` Embedding 模型，大幅提升中文搜索效果，可通过 `CORTEX_EMBEDDING_MODEL` 切换
- **记忆更新 API** — 新增 `PUT /v1/memories/{id}`，支持原地更新记忆内容、标签、重要度等字段
- **CORS 配置** — 支持通过 `CORTEX_CORS_ORIGINS` 配置跨域访问
- **Docker 部署** — 新增 `Dockerfile` 和 `docker-compose.yml`，支持一键容器化部署

### 🔧 改进
- **结构化日志** — 统一日志格式，关键操作均有日志记录，通过 `CORTEX_LOG_LEVEL` 控制级别
- **SQLite 并发安全** — 使用 `threading.local()` 线程级连接管理 + `busy_timeout` 避免锁争抢
- **全局异常处理** — 统一错误响应格式 `{"error": ..., "detail": ...}`，区分验证错误、业务错误和系统错误

### 📦 依赖
- 新增 `sentence-transformers` 依赖

## [0.1.0] - 2026-02-20

### 🎉 首次发布 — MVP
- **数据模型** — MemoryFragment / Tenant / Project / ApiKey (Pydantic v2)
- **存储层** — ChromaDB 向量存储 + SQLite 元数据存储
- **业务层** — MemoryManager (add/search/history/delete/stats) + ChannelManager
- **REST API** — FastAPI + API Key 认证中间件，10 个端点
- **测试** — 47 个测试全部通过
