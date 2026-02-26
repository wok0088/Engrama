"""
Engrama 统一日志配置

提供结构化日志输出，关键操作均有日志记录。
支持通过环境变量 ENGRAMA_LOG_LEVEL 控制日志级别。
"""

import logging
import os
import sys
import threading

_logger_lock = threading.Lock()


def get_logger(name: str) -> logging.Logger:
    """
    获取统一配置的 Logger 实例

    Args:
        name: 日志名称（通常传 __name__）

    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(f"engrama.{name}")

    # 使用锁保护 handler 检查和添加，避免多线程竞态导致重复 handler
    with _logger_lock:
        if not logger.handlers:
            level = os.getenv("ENGRAMA_LOG_LEVEL", "INFO").upper()
            logger.setLevel(getattr(logging, level, logging.INFO))

            handler = logging.StreamHandler(sys.stderr)
            handler.setLevel(getattr(logging, level, logging.INFO))

            formatter = logging.Formatter(
                fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

    return logger
