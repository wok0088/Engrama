# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/) 版本规范。

## [0.5.1] - 2026-02-25

### 🔒 安全加固
- **强制阻断渠道管理越权漏洞（CVE 防护级别）** — `api/middleware.py` 严格拦截未配置 `ENGRAMA_ADMIN_TOKEN` 时的渠道侧接口调用。此前在未配置 Token 的开发环境模式下，系统会放行租户注册请求。由于此配置往往被粗心用户直接带入生产环境从而导致“裸奔”，现已完全废弃这种包容行为，改为全环境强制 `403 Forbidden` 拦截，杜绝基座资源被非法滥用注册的风险。

### 📚 文档与工程规范
- **重构为 Diátaxis 架构** — 将原大而全的单体文档重新整理，精简 `README.md`，新增独立的 `TUTORIAL-how-to.md` 指南文件。
- **自动化测试注入** — 为集成测试组件和 `conftest.py` 提供全量的 Mock 鉴权请求头注入，以应对收紧后的安全拦截策略。

## [0.5.0] - 2026-02-24

### 🚀 重大重构
- **独立的 Embedding 推理引擎** — 将模型从主进程内嵌的 `SentenceTransformer` 迁移至外部的文本嵌入推理引擎 (TEI)，使用高性能 Rust 编写。根除 Mac MPS 和多进程下加载模型造成的内存泄漏或 OutOfMemory 奔溃。
- **存储后端升级** — 将原本基于文件系统的 SQLite 与 ChromaDB 升级为正式的 PostgreSQL 与 Qdrant 组合。新增 `PostgresMetaStore` 和 `QdrantStore` 控制类，提升稳定性、性能和可扩展性。
- **多容器编排** — 提供开箱即用的 Docker Compose 堆栈，支持一键部署 Postgres, Qdrant 和分离的 TEI 服务引擎。
- **环境安全配置升级** — 引入 `python-dotenv`。全面清理代码中的硬编码密码，迁移至 `.env` 文件。支持基于 `.env.example` 快速启动，`.gitignore` 拦截机制确保生产密钥安全。
- **测试防误删机制 (Failsafe)** — 集成测试包含清表操作。在测试引导配置入口添加严格的环境和数据库名字母校验锁，防止误操作引发生产库数据销毁 (`DROP/TRUNCATE`) 漏洞。

## [0.4.4] - 2026-02-24

### 📦 依赖修复
- **移除 Numpy/Transformers 降级限制** — 解决了由包体冲突导致的冗余降级限制，更新为 `transformers>=4.41.0` 与 `numpy>=1.26.0`。

### 🐛 缺陷修复
- **Python 3.12 警告清理** — `meta_store.py` 修复了 SQLite 原生驱动对 `datetime` 直接插入时报出的 `DeprecationWarning`，将字段存储转为显式的 `.isoformat()` 字符串序列化，令全量测试清爽通过。

## [0.4.3] - 2026-02-23

### 🐛 缺陷修复
- **速率限制器逻辑修复** — `rate_limiter.py` 修复了 `del` 后被 `defaultdict` 立即重建导致清理无效的 bug，重构为先过滤再判断的正确流程。
- **SQLite 外键约束生效** — `meta_store.py` 新增 `PRAGMA foreign_keys=ON`，使表定义中的 `FOREIGN KEY` 声明真正生效，防止数据完整性被破坏。
- **级联删除适配外键** — 删除租户/项目时，关联的 API Key 从软删除改为物理删除，与启用的外键约束保持一致，消除 `IntegrityError`。
- **Collection 名称哈希碰撞风险降低** — `vector_store.py` 将 `_collection_name` 的截断后缀哈希从 MD5 改为 SHA-256，碰撞概率从 2^-32 降至 2^-32（同样 8 字符，但 SHA-256 分布更均匀）。
- **`_sanitize` 覆盖面扩大** — 使用正则 `[^a-zA-Z0-9_]` 替代手工替换 `-` 和 `@`，能正确处理空格、斜杠、点号、中文等 ChromaDB 不允许的字符。

### 🔧 改进
- **API 响应字段语义修正** — `SearchResultResponse` 和 `HistoryResponse` 的 `total` 字段重命名为 `count`，明确表示"本次返回数量"而非误导性的"总匹配数"。
- **`get_stats` 加载上限** — 统计查询增加 `limit=10000` 防护，避免海量记忆时一次性加载全部 metadata 导致内存问题。
- **测试基础设施优化** — 提取重复的 `tmp_dir` fixture 到 `tests/conftest.py`，消除 6 个测试文件中的重复定义；`test_mcp.py` 改用 `monkeypatch.setenv` 替代直接操作 `os.environ`，确保异常退出时环境变量被正确清理。

## [0.4.2] - 2026-02-23

### 🐛 缺陷修复 & 安全加固
- **访问控制修复** — `rate_limiter.py` 严格遵守运算符优先级，解决短路评估可能导致的隐患，同时清理空列表键值移除内存泄漏风险。
- **防止时序攻击** — `api/middleware.py` 使用 `hmac.compare_digest` 实现了对 Admin Token 的常量时间对比防护。
- **中间件提纯** — 消除 `api/main.py` 关于 `MetaStore` 的双重重初始化竞争，统一拦截器从 `app.state` 获取实例引用，节约系统开支。
- **配置规范性** — `middleware.py` 修复了 `AUTH_EXCLUDED_PREFIXES` 声明却未使用的缺陷；`models.py` 将 `tags` 的默认参数标准化为 `Field(default_factory=list)` 避免 Pydantic 解析问题。
- **逻辑优化** — `memories.py` 移除对空字符串做强硬依赖的业务判断；`engrama/channel_manager.py` 移除冗余重复的业务日志；`config.py` 收敛各处零散定义统一 `API_VERSION` 来源。
- **测试覆盖增强** — 重构与补充大量边界化测试集（由 69 增至 74 项集成用例全部通过），涵盖管理员权限熔断、非法 Key 跨域、流量控制溢出等异常用例。

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
- **渠道管理 API 认证** — 新增 `X-Admin-Token` 管理员认证，生产环境通过 `ENGRAMA_ADMIN_TOKEN` 环境变量配置
- **输入长度限制** — content（10000 字符）、name（100 字符）、tags（20 个）等关键字段增加校验
- **速率限制** — 基于内存的滑动窗口限制，通过 `ENGRAMA_RATE_LIMIT` 环境变量配置每分钟最大请求数

### ✨ 新功能
- **中文语义搜索** — 默认使用 `BAAI/bge-small-zh-v1.5` Embedding 模型，大幅提升中文搜索效果，可通过 `ENGRAMA_EMBEDDING_MODEL` 切换
- **记忆更新 API** — 新增 `PUT /v1/memories/{id}`，支持原地更新记忆内容、标签、重要度等字段
- **CORS 配置** — 支持通过 `ENGRAMA_CORS_ORIGINS` 配置跨域访问
- **Docker 部署** — 新增 `Dockerfile` 和 `docker-compose.yml`，支持一键容器化部署

### 🔧 改进
- **结构化日志** — 统一日志格式，关键操作均有日志记录，通过 `ENGRAMA_LOG_LEVEL` 控制级别
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
