"""
Engrama 配置管理

集中管理所有配置项，支持通过环境变量覆盖默认值。

注意：所有配置值在模块导入时固定，运行时修改环境变量不会生效。
测试中需要覆盖配置时，请使用 monkeypatch.setattr(config, ...) 而非 os.environ。
"""

import os
from pathlib import Path


# 项目根目录
_PROJECT_ROOT = Path(__file__).parent.parent

# 数据持久化目录
DATA_DIR = Path(os.getenv("ENGRAMA_DATA_DIR", str(_PROJECT_ROOT / "data")))

# ChromaDB 配置
CHROMA_PERSIST_DIR = DATA_DIR / "chroma_db"

# SQLite 配置
SQLITE_DB_PATH = DATA_DIR / "engrama_meta.db"

# 数据库类型 (sqlite 或 postgres)
DB_TYPE = os.getenv("ENGRAMA_DB_TYPE", "sqlite")

# PostgreSQL 连接 URI (如 postgresql://user:pass@localhost:5432/engrama)
PG_URI = os.getenv("ENGRAMA_PG_URI", "")

# Redis 配置 (如 redis://localhost:6379/0)
REDIS_URL = os.getenv("ENGRAMA_REDIS_URL", "")

# Embedding 模型
# 默认使用项目内的 BAAI/bge-m3（多语言 Embedding 模型，支持中英日韩俄等 100+ 语言）
# 模型文件存放在 data/models/bge-m3/，不依赖 ~/.cache 缓存
# 可通过环境变量切换为其他 sentence-transformers 兼容模型
EMBEDDING_MODEL = os.getenv("ENGRAMA_EMBEDDING_MODEL", str(DATA_DIR / "models" / "bge-m3"))

# 搜索默认参数
DEFAULT_SEARCH_LIMIT = 10
DEFAULT_HISTORY_LIMIT = 50

# API 配置
from engrama import __version__
API_TITLE = "Engrama — 通用 AI 记忆中间件"
API_VERSION = __version__
API_DESCRIPTION = "为各类 AI 项目提供按渠道接入、按用户隔离的记忆存储与语义检索服务。"

# 管理员 Token（用于渠道管理 API 的认证）
# ⚠️ 生产环境必须设置：export ENGRAMA_ADMIN_TOKEN=your_secret_token
ADMIN_TOKEN = os.getenv("ENGRAMA_ADMIN_TOKEN", "")

# CORS 配置
# 多个域名用逗号分隔，如 "http://localhost:3000,https://example.com"
# 设置为 "*" 允许所有域（仅开发环境使用）
CORS_ORIGINS = os.getenv("ENGRAMA_CORS_ORIGINS", "*")

# 速率限制配置（每分钟最大请求数，0 表示不限制）
RATE_LIMIT_PER_MINUTE = int(os.getenv("ENGRAMA_RATE_LIMIT", "0"))

# 输入长度限制
MAX_CONTENT_LENGTH = 10000  # 记忆内容最大字符数
MAX_NAME_LENGTH = 100       # 名称最大字符数
MAX_TAGS_COUNT = 20         # 标签最大数量

# 不需要认证的路径前缀（渠道管理现在需要单独管理管理员 Token）
# /health 不在此列表中，因为 middleware 已硬编码 path in ("/", "/health") 跳过
AUTH_EXCLUDED_PREFIXES = ["/docs", "/redoc", "/openapi.json"]
