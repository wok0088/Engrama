"""
共享测试 Fixtures

提取各测试文件中重复的 tmp_dir fixture，统一在此定义。
"""

import os
import shutil
import tempfile
import pytest
from dotenv import load_dotenv

# --- 环境隔离与自动化配置加载 ---
def _setup_test_env():
    env_file = ".env"
    test_env_file = ".env.test"
    
    # 场景1：当执行 ENGRAMA_ENV=test 时，确保 .env.test 存在，若不存在则基于 .env 自动生成
    if os.getenv("ENGRAMA_ENV") == "test":
        if not os.path.exists(test_env_file):
            if not os.path.exists(env_file):
                pytest.exit("🔥 错误: 找不到基础的 .env 文件，无法自动生成 .env.test！")
            
            # 读取基础配置并注入测试环境变量
            with open(env_file, "r") as f:
                content = f.read()
            
            # 使用简单的正则或替换追加 _test 到数据库 URI
            import re
            
            # 替换 PG_URI，给数据库名加上 _test
            # 例如 postgresql://user:pass@host:port/engrama -> postgresql://user:pass@host:port/engrama_test
            content = re.sub(
                r"(ENGRAMA_PG_URI=.*\/[a-zA-Z0-9_-]+)(?!\w)", 
                r"\g<1>_test", 
                content
            )
            
            # 增加或替换 Qdrant 测试 Collection Name
            if "ENGRAMA_QDRANT_COLLECTION=" in content:
                content = re.sub(
                    r"ENGRAMA_QDRANT_COLLECTION=.*", 
                    "ENGRAMA_QDRANT_COLLECTION=test_memories", 
                    content
                )
            else:
                content += "\nENGRAMA_QDRANT_COLLECTION=test_memories\n"
                
            # 替换 Redis 数据库号（假设默认是 /0，测试时换成 /1，避免跟生产限流数据冲突）
            if "ENGRAMA_REDIS_URL=" in content:
                content = re.sub(
                    r"(ENGRAMA_REDIS_URL=.*)/0(?!\w)", 
                    r"\g<1>/1", 
                    content
                )
            
            with open(test_env_file, "w") as f:
                f.write(content)
            
            print("✨ 自动生成了隔离的测试环境配置文件: .env.test")
        
        # 强制加载测试环境变量，覆盖当前系统变量
        load_dotenv(test_env_file, override=True)
        print("🔧 已加载测试配置: .env.test")
        
    else:
        # 场景2：如果没带 ENGRAMA_ENV=test，但当前发现有 .env.test 文件，给予明确提示并阻断
        if os.path.exists(test_env_file):
            pytest.exit(
                "🚨 环境安全警告！\n"
                "检测到存在 .env.test 配置文件，但您没有使用 ENGRAMA_ENV=test 启动测试。\n"
                "为了安全与配置的一致性，请使用此命令运行测试:\n"
                "👉 ENGRAMA_ENV=test pytest"
            )

# 必须在所有 engrama 内部模块导入前执行测试环境加载
_setup_test_env()

from engrama import config
import psycopg
from psycopg.errors import DuplicateDatabase
from qdrant_client import QdrantClient
from psycopg_pool import ConnectionPool
from engrama.store.qdrant_store import COLLECTION_NAME

@pytest.fixture
def tmp_dir(tmp_path):
    return str(tmp_path)

@pytest.fixture(scope="session")
def db_pool():
    """全局共享的 PostgreSQL 连接池"""
    is_test_env = os.getenv("ENGRAMA_ENV") == "test"
    is_test_db = "test" in config.PG_URI.lower()
    
    # 终极安全锁：禁止在非测试环境清理数据
    if not (is_test_env and is_test_db):
        pytest.exit(
            "🚨 危险操作拦截！\n"
            "检测到当前运行环境未明确标记为测试环境 (ENGRAMA_ENV!=test) 或数据库名不含 'test'。\n"
            "为防止误删生产数据，测试已被强制终止！\n"
            f"当前连接的库: {config.PG_URI}\n"
            "👉 本地跑测试请使用命令: ENGRAMA_ENV=test pytest"
        )
        
    # 尝试自动建库 (需要连接到默认数据库来进行建库操作)
    import urllib.parse
    parsed_uri = urllib.parse.urlparse(config.PG_URI)
    db_name = parsed_uri.path.lstrip('/')
    default_db_uri = config.PG_URI.replace(db_name, "postgres")
    
    try:
        # 尝试使用 autocommit 连接到默认库 postgres 来创建测试库
        with psycopg.connect(default_db_uri, autocommit=True) as sys_conn:
            with sys_conn.cursor() as sys_cur:
                print(f"尝试检查并自动创建测试数据库: {db_name}")
                sys_cur.execute(f"CREATE DATABASE {db_name} OWNER {parsed_uri.username};")
                print(f"✨ 测试数据库 {db_name} 已自动创建。")
    except DuplicateDatabase:
        pass # 库已存在，直接略过
    except Exception as e:
        print(f"⚠️ 自动创建测试数据库失败，但仍将尝试走连接池连 {db_name} (原因: {e})")
        
    pool = ConnectionPool(config.PG_URI, min_size=1, max_size=5, open=True)
    yield pool
    pool.close()

@pytest.fixture(scope="session")
def qdrant():
    """全局共享的 Qdrant 客户端"""
    client = QdrantClient(
        url=f"http://{config.QDRANT_HOST}:{config.QDRANT_PORT}",
        api_key=config.QDRANT_API_KEY if config.QDRANT_API_KEY else None
    )
    yield client
    client.close()

@pytest.fixture(scope="session", autouse=True)
def ensure_qdrant_collection(qdrant):
    """确保 Qdrant Collection 在测试会话中存在（只创建一次，避免 94 次重建）"""
    from qdrant_client.http import models as rest
    # 先尝试删除旧的，确保干净状态
    try:
        qdrant.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=rest.VectorParams(
            size=config.EMBEDDING_VECTOR_SIZE,
            distance=rest.Distance.COSINE
        )
    )
    # 建索引（整个测试会话只做一次）
    for field in ["tenant_id", "project_id", "user_id", "memory_type", "session_id"]:
        qdrant.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field,
            field_schema=rest.PayloadSchemaType.KEYWORD
        )
    yield


@pytest.fixture(autouse=True)
def clean_databases(db_pool, qdrant):
    """每次测试前清理数据库，保留 Collection 结构和索引，只清除数据点"""
    # 1. 清理 PostgreSQL 数据
    with db_pool.connection() as conn:
        with conn.cursor() as cur:
            # 使用 CASCADE 级联清理，忽略尚未建表的错误
            try:
                cur.execute("TRUNCATE TABLE memory_fragments, projects, api_keys, tenants CASCADE")
                conn.commit()
            except Exception:
                conn.rollback()

    # 2. 清理 Qdrant Collection 中的所有点（保留结构和索引）
    from qdrant_client.http import models as rest
    try:
        # 滚动获取所有点的 ID 并批量删除
        all_ids = []
        offset = None
        while True:
            records, next_offset = qdrant.scroll(
                collection_name=COLLECTION_NAME,
                limit=1000,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            if not records:
                break
            all_ids.extend([r.id for r in records])
            if next_offset is None:
                break
            offset = next_offset
        if all_ids:
            qdrant.delete(
                collection_name=COLLECTION_NAME,
                points_selector=rest.PointIdsList(points=all_ids),
            )
    except Exception:
        pass

    yield

@pytest.fixture(scope="session", autouse=True)
def setup_test_config():
    """全局设置测试配置，替换原有的 monkeypatch 机制"""
    d = tempfile.mkdtemp()
    config.DATA_DIR = d
    if not config.ADMIN_TOKEN:
        import secrets
        config.ADMIN_TOKEN = secrets.token_hex(32)
    yield
    shutil.rmtree(d, ignore_errors=True)
