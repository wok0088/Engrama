"""
Cortex 配置管理

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
SQLITE_DB_PATH = DATA_DIR / "cortex_meta.db"

# 搜索默认参数
DEFAULT_SEARCH_LIMIT = 10
DEFAULT_HISTORY_LIMIT = 50

# API 配置
API_TITLE = "Cortex — 通用 AI 记忆中间件"
API_VERSION = "0.1.0"
API_DESCRIPTION = "为各类 AI 项目提供按渠道接入、按用户隔离的记忆存储与语义检索服务。"

# 不需要认证的路径前缀
AUTH_EXCLUDED_PREFIXES = ["/v1/channels", "/docs", "/redoc", "/openapi.json", "/health"]
