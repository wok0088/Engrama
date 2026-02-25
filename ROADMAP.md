# Engrama — 通用 AI 记忆中间件 版本规划

> **Engrama** 是一个通用的 AI 记忆中间件（Memory-as-a-Service），为各类 AI 项目提供"按渠道接入、按用户隔离"的记忆存储与语义检索服务。

> [!TIP]
> **开发策略**：建议先体验 Mem0（自部署），带着真实痛点再做 Engrama——没被 Mem0 "伤害"过，就不知道 Engrama 该往哪里使劲。详见 [MEM0_ANALYSIS.md](file:///Users/nil/storage/Code/Lab/engrama/MEM0_ANALYSIS.md)。

---

## 核心设计原则

1. **轻量优先**：能不依赖 LLM 就不依赖，基础功能零 LLM 成本
2. **通用性**：不绑定任何具体业务场景，任何 AI 项目都能通过 REST API / MCP 接入
3. **三层隔离**：Tenant（租户）→ Project（项目）→ User（用户），数据天然隔离
4. **为将来预留**：记忆片段预留 `hit_count` 和 `importance` 字段，为检索优化和智能淘汰做数据准备

---

## 数据模型设计

### 组织层级

```
Tenant（租户：携程 / 个人开发者）
  └── Project（项目：酒店 AI / 玄学 AI）
       └── User（用户：张三 / 李四）
            └── Memory Fragment（记忆片段）
```

### 记忆分类

| 类型     | memory_type  | 说明           | 示例                    |
| -------- | ------------ | -------------- | ----------------------- |
| 事实记忆 | `factual`    | 客观事实信息   | "生日是 1990-03-15"     |
| 偏好记忆 | `preference` | 主观喜好       | "喜欢安静的环境"        |
| 经历记忆 | `episodic`   | 具体交互事件   | "2025-01-15 咨询过八字" |
| 会话记忆 | `session`    | 对话上下文消息 | 具体的一轮对话          |

### 记忆片段字段

```python
class MemoryFragment:
    id: str                    # 唯一 ID
    tenant_id: str             # 租户
    project_id: str            # 项目
    user_id: str               # 用户
    content: str               # 记忆内容
    memory_type: str           # factual / preference / episodic / session
    role: str | None           # user / assistant / system（仅 session 类型）
    session_id: str | None     # 可选，会话 ID（仅 session 类型）
    tags: list[str]            # 标签
    hit_count: int             # 被检索次数（用于排序优化和智能淘汰）
    importance: float          # 重要度评分（用于检索排序和缓存预热）
    created_at: datetime       # 创建时间
    updated_at: datetime       # 更新时间
    metadata: dict | None      # 扩展元数据
```

---

## 已完成版本

> 详细的变更日志见 [CHANGELOG.md](file:///Users/nil/storage/Code/Lab/engrama/CHANGELOG.md)。

### [0.1.0] — 2026-02-20 · MVP：存-取-搜核心链路 ✅

跑通"存储记忆 → 获取历史 → 语义搜索"的完整链路，通过 REST API 对外提供服务。

<details>
<summary>详细功能列表（点击展开）</summary>

#### 数据模型层
- [x] `MemoryFragment` 模型（Pydantic v2）
- [x] `Tenant`、`Project` 模型
- [x] 记忆类型枚举（factual / preference / episodic / session）

#### 存储层
- [x] ChromaDB 向量存储（语义搜索）
- [x] SQLite 元数据存储（租户、项目、API Key）

#### 业务 API 层（MemoryManager）
- [x] `add()` / `add_message()` / `search()` / `get_history()` / `list_memories()` / `delete()` / `get_stats()`

#### 渠道管理（ChannelManager）
- [x] 租户注册 / 项目创建删除 / API Key 生成验证

#### REST API 层（FastAPI）
- [x] 记忆 CRUD + 搜索 + 会话历史 + 渠道管理（10 个端点）
- [x] API Key 认证中间件

#### 测试
- [x] 47 个测试全部通过

</details>

### [0.2.0] — 2026-02-22 · 安全加固 + 中文搜索 ✅

- [x] 管理员 Token 认证（`X-Admin-Token`）
- [x] 输入长度限制 / CORS 配置 / 速率限制（滑动窗口）
- [x] 中文语义搜索（`BAAI/bge-small-zh-v1.5`）
- [x] 记忆更新 API（`PUT /v1/memories/{id}`）
- [x] Docker 部署（`Dockerfile` + `docker-compose.yml`）
- [x] 结构化日志 / 全局异常处理 / SQLite 并发安全

#### [0.2.1] — 2026-02-23 · 并发修复

- [x] 修复事件循环阻塞（路由从 `async def` 改为 `def`）
- [x] Collection 粒度从 per-user 优化为 per-project

### [0.3.0] — 2026-02-23 · MCP Server ✅

- [x] MCP (Model Context Protocol) 接口，6 个 Tools（`add_memory` / `search_memory` / `add_message` / `get_history` / `delete_memory` / `get_user_stats`）
- [x] 支持 stdio / SSE 两种传输
- [x] 可接入 Claude Desktop、Cursor 等 MCP 客户端

### [0.4.0 ~ 0.4.4] — 2026-02-23 ~ 2026-02-24 · 鉴权体系 + 安全审计 ✅

- [x] **[0.4.0]** API Key 分级（项目级 B 端 + 用户级 C 端）/ MCP 鉴权 / Tool 签名降维防 IDOR / 越权防护 403 / 多语言 Embedding `BAAI/bge-m3`
- [x] **[0.4.1]** `GET /v1/users/me/stats` 路由 / 跨租户绑定 Project 漏洞修复 / 中间件线程池委派
- [x] **[0.4.2]** `hmac.compare_digest` 防时序攻击 / 中间件提纯 / 测试覆盖增至 74 项
- [x] **[0.4.3]** 速率限制器逻辑修复 / SQLite 外键约束生效 / 级联删除适配 / 测试基础设施优化
- [x] **[0.4.4]** 移除 numpy/transformers 降级限制 / Python 3.12 DeprecationWarning 修复

### [0.5.0] — 2026-02-24 · 生产化基础设施升级（当前版本）✅

- [x] **存储后端升级**：ChromaDB + SQLite → **Qdrant + PostgreSQL**
- [x] **独立推理引擎**：进程内 SentenceTransformer → **TEI (Text Embeddings Inference, Rust)**
- [x] **多语言 Embedding**：`BAAI/bge-m3`（1024 维，支持中英文）
- [x] **多容器编排**：Docker Compose 一键部署（Postgres + Qdrant + Redis + TEI）
- [x] **Redis 分布式限流**
- [x] **环境安全配置**：`python-dotenv` + `.env` 集中管理
- [x] **测试防误删机制**：`ENGRAMA_ENV=test` 安全锁，94 个测试全部通过

### [0.5.1] - 2026-02-25 · 安全热修复与文档架构重构（当前版本）✅

- [x] **强制阻塞无凭证渠道注册**：`middleware.py` 安全收紧，取消开发环境兼容设定，全级别强制 `ENGRAMA_ADMIN_TOKEN` 拦截。
- [x] **Diátaxis 规范重塑**：重构项目自述文件体系，拆分操作指南教程。
- [x] 测试固件注入全局 Mock Token 适配安全更新。

---

## 当前版本状态

| 版本 | 状态 | 当前能力 |
|---|---|---|
| **v0.5.1** | ✅ 当前版本 | 完整的存-取-搜链路 + 生产级基础设施 + MCP + 鉴权体系 + 严格渠道保护 |
| v0.5.0 | 🔖 历史版本 | 基础设施升级（TEI + Postgres + Qdrant集成） |

### 已具备的完整能力

| 能力 | 说明 |
|---|---|
| REST API（13 个端点）| 记忆 CRUD + 搜索 + 会话历史 + 渠道管理 + 统计 |
| MCP Server（6 个 Tools）| AI 可直接调用 |
| 三层隔离 | Tenant → Project → User |
| API Key 分级 | 项目级 Key（B 端）+ 用户级 Key（C 端） |
| 语义搜索 | 基于 BGE-m3 多语言 Embedding |
| 安全体系 | Admin Token + API Key 哈希 + 越权防护 + 速率限制 |
| 存储 | PostgreSQL（元数据）+ Qdrant（向量）|
| 部署 | Docker Compose 一键部署 |

---

## 未来版本规划

### V1.0 — 稳定化 + 开发者体验（1-2 周）

> **目标**：API 定型、文档完善，达到首个正式发布标准。

- [ ] **API 稳定化**：确认现有 API 不再变动，打上 `v1.0.0` 标签
- [ ] **OpenAPI 文档完善**：各端点补充完整的 description、example
- [ ] **错误码规范化**：统一错误码体系（目前靠 HTTP status code + 中文 detail）
- [ ] **依赖清理**：移除 `requirements.txt` 中不再使用的 `sentence-transformers` / `transformers` / `numpy`（已迁移至 TEI）
- [ ] **Swagger UI 增强**：让 `/docs` 页面可以直接测试（预填 API Key 等）
- [ ] **Python SDK 封装**（可选）：一个轻量的 `engrama-client` 包

### V1.1 — 可观测性 + 运维加固（2-3 周）

> **目标**：让生产环境运维有抓手。

- [ ] **健康检查增强**：`/health` 检查 PG + Qdrant + TEI 三个后端连通性
- [ ] **Prometheus 指标暴露**：请求延迟、Embedding 耗时、存储量等
- [ ] **日志结构化输出**：JSON 格式日志，方便 ELK / Loki 采集
- [ ] **连接池监控**：PG 连接池状态可观测
- [ ] **优雅停机**：确保 SIGTERM 时连接池正确关闭

---

### V2.0 — 记忆智能化（1-2 月）

> **目标**：让记忆系统从"傻存傻取"进化为"有组织、会整理"。

#### 核心功能

- [ ] **记忆冲突检测**（无需 LLM）：新记忆存入时通过向量相似度检测与已有记忆的矛盾（如"喜欢安静" vs "喜欢热闹"），阈值可配置
- [ ] **动态遗忘 / 淘汰策略**：基于 `hit_count` + `importance` + 时间衰减的自动清理策略
    - `score = importance × decay(time_since_last_hit)`
    - 长期未被检索的低重要度记忆自动归档或删除
- [ ] **重要度自动评分**：基于 `hit_count` 和内容特征的规则评分（无需 LLM）

#### 可选 LLM 增强（需用户自带 LLM）

- [ ] **智能提取模式**：从对话中自动提取事实 / 偏好（参考 Mem0 的 Extraction 阶段），与手动存入并存
- [ ] **记忆冲突解决**：LLM 判断新旧记忆矛盾时执行 ADD / UPDATE / DELETE / NOOP
- [ ] **搜索 Query 优化**：LLM 改写用户查询，提升语义搜索精度
- [ ] **会话摘要**：长会话自动生成摘要

> [!IMPORTANT]
> V2 的 LLM 增强功能设计为**可选模式**，用户需自行配置 LLM API。Engrama 的基础功能始终保持零 LLM 成本。

---

### V3.0 — 平台化（2-3 月）

> **目标**：从开发者工具进化为可运营的平台。

- [ ] **管理后台 Web UI**：租户 / 项目 / API Key / 记忆管理的可视化界面
- [ ] **用量统计与计费**：按租户的 API 调用量统计
- [ ] **SDK 发布**：Python SDK、JavaScript SDK（npm 包）
- [ ] **自定义提取规则**：每个 Project 可定义自己的"关注点"Prompt 模板
- [ ] **批量操作 API**：批量导入 / 导出记忆

---

### V4.0 — 高级记忆能力（3-6 月）

> **目标**：对标 Mem0 / MemOS，具备高级记忆管理能力。

- [ ] **知识图谱**：记忆之间的关系建模（实体 - 关系 - 实体）
- [ ] **多模态记忆**：支持图片、音频等记忆类型
- [ ] **跨项目记忆共享**：Tenant 级别的记忆可见性控制
- [ ] **多 Agent 共享记忆**：支持 Agent 间的记忆共享协议
- [ ] **Embedding 模型可选微调**：用高频检索数据微调向量模型，提升领域搜索精度（可选优化项，非必需）

---

## 技术栈

| 层级 | 技术 | 说明 |
|---|---|---|
| 语言 | Python 3.11+ | 核心语言 |
| Web 框架 | FastAPI | REST API 层 |
| MCP | mcp (FastMCP) | AI 模型直接调用（stdio / SSE） |
| 向量数据库 | Qdrant | 独立的语义搜索引擎容器 |
| Embedding | TEI (Text Embeddings Inference) | 单独的高性能 Rust 推理引擎 |
| 关系型存储 | PostgreSQL | 租户 / 项目 / Key / 记忆元数据 |
| 缓存 / 限流 | Redis | 分布式速率限制（可选） |
| 数据验证 | Pydantic v2 | 类型安全的数据模型 |
| 测试 | pytest | 94 个集成测试 |
| 容器化 | Docker + Docker Compose | 多容器编排部署 |

---

## Engrama 与微调/专一模型的关系

### 核心定位：Engrama 是"笔记本"，不是"大脑"

```
使用方的系统
├── 通用大模型（GPT/Claude/Deepseek）  ← 使用方自己选，Engrama 不管
├── 微调/专一模型                       ← 使用方按需训练，Engrama 不管
└── Engrama（记忆中间件）                ← 只负责存、取、搜记忆
```

### 需要微调吗？——基于行业调研的结论

> **主流记忆系统（Mem0 / Letta / Zep / MemOS）均不做内部模型微调，全部使用预训练模型。**

| 系统               | 内部是否微调模型 | 实际做法                              |
| ------------------ | ---------------- | ------------------------------------- |
| Mem0（37k+ stars） | ❌ 不微调         | 使用预训练 Embedding + LLM 做事实提取 |
| Letta/MemGPT       | ❌ 不微调         | LLM 通过 tool-calling 自编辑记忆      |
| Zep                | ❌ 不微调         | 预训练模型 + 时序知识图谱             |
| MemOS              | ❌ 不微调         | MemCube 抽象 + 规则调度器             |

**结论**：V1-V3 完全不需要模型微调。V4 可选微调 Embedding 模型（研究显示可提升 7-22% 检索精度），但这是锦上添花，不是核心功能。

### `hit_count` 和 `importance` 字段的真正用途

| 字段         | 实际用途                                                 |
| ------------ | -------------------------------------------------------- |
| `hit_count`  | 检索排序加权、缓存预热、智能淘汰决策                     |
| `importance` | 记忆优先级排序、存储分层（热/温/冷）、与新记忆的冲突解决 |
