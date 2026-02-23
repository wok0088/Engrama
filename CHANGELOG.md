# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/) 版本规范。

## [0.3.0] - 2026-02-23

### ✨ 新功能
- **MCP Server** — 通过 MCP (Model Context Protocol) 协议让 AI 模型直接调用 Cortex 记忆功能
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
