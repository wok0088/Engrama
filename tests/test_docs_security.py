"""
测试生产环境下 Swagger UI 的接口屏蔽情况
"""
import pytest
from fastapi.testclient import TestClient

from engrama import config
from api.main import create_app

def test_docs_hidden_in_prod(monkeypatch):
    """
    当 ENGRAMA_ENV 为 prod 时，/docs 和 /openapi.json 应该返回 404 Not Found
    """
    # 模拟环境配置为 prod
    monkeypatch.setattr(config, "ENV_NAME", "prod")
    
    # 在 prod 环境下重新初始化 App
    prod_app = create_app()
    with TestClient(prod_app) as client:
        # 测试根目录提示变更
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["docs"] == "Disabled in Production"

        # 测试详细文档被禁用 (HTTP 404)
        resp = client.get("/docs")
        assert resp.status_code == 404
        
        resp = client.get("/openapi.json")
        assert resp.status_code == 404

def test_docs_available_in_dev(monkeypatch):
    """
    当 ENGRAMA_ENV 不为 prod 时 (譬如 dev/test)，文档正常工作
    """
    monkeypatch.setattr(config, "ENV_NAME", "dev")
    
    dev_app = create_app()
    with TestClient(dev_app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["docs"] == "/docs"

        # dev 环境下请求 openapi.json 应该正常返回 200
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
