"""
共享测试 Fixtures

提取各测试文件中重复的 tmp_dir fixture，统一在此定义。
"""

import shutil
import tempfile

import pytest


@pytest.fixture
def tmp_dir():
    """创建临时目录，测试后自动清理"""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)
