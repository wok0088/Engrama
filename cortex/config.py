"""
Engrama 配置管理

集中管理所有配置项，支持通过环境变量覆盖默认值。
"""

import os
from pathlib import Path


# 项目根目录
_PROJECT_ROOT = Path(__file__).parent.parent

# 数据持久化目录
DATA_DIR = Path(os.getenv("CORTEX_DATA_DIR", str(_PROJECT_ROOT / "data")))

# ChromaDB 配置
CHROMA_PERSIST_DIR = DATA_DIR / "chroma_db"

# SQLite 配置
SQLITE_DB_PATH = DATA_DIR / "engrama_meta.db"

# Embedding 模型
# 默认使用项目内的 BAAI/bge-m3（多语言 Embedding 模型，支持中英日韩俄等 100+ 语言）
# 模型文件存放在 data/models/bge-m3/，不依赖 ~/.cache 缓存
# 可通过环境变量切换为其他 sentence-transformers 兼容模型
EMBEDDING_MODEL = os.getenv("CORTEX_EMBEDDING_MODEL", str(DATA_DIR / "models" / "bge-m3"))

# 搜索默认参数
DEFAULT_SEARCH_LIMIT = 10
DEFAULT_HISTORY_LIMIT = 50

# API 配置
API_TITLE = "Engrama — 通用 AI 记忆中间件"
API_VERSION = "0.4.0"
API_DESCRIPTION = "为各类 AI 项目提供按渠道接入、按用户隔离的记忆存储与语义检索服务。"

# 管理员 Token（用于渠道管理 API 的认证）
# ⚠️ 生产环境必须设置：export CORTEX_ADMIN_TOKEN=your_secret_token
ADMIN_TOKEN = os.getenv("CORTEX_ADMIN_TOKEN", "")

# CORS 配置
# 多个域名用逗号分隔，如 "http://localhost:3000,https://example.com"
# 设置为 "*" 允许所有域（仅开发环境使用）
CORS_ORIGINS = os.getenv("CORTEX_CORS_ORIGINS", "*")

# 速率限制配置（每分钟最大请求数，0 表示不限制）
RATE_LIMIT_PER_MINUTE = int(os.getenv("CORTEX_RATE_LIMIT", "0"))

# 输入长度限制
MAX_CONTENT_LENGTH = 10000  # 记忆内容最大字符数
MAX_NAME_LENGTH = 100       # 名称最大字符数
MAX_TAGS_COUNT = 20         # 标签最大数量

# 不需要认证的路径前缀（注意：渠道管理现在需要管理员 Token）
AUTH_EXCLUDED_PREFIXES = ["/v1/channels", "/docs", "/redoc", "/openapi.json", "/health"]
