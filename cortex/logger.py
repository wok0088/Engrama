"""
Engrama 统一日志配置

提供结构化日志输出，关键操作均有日志记录。
支持通过环境变量 CORTEX_LOG_LEVEL 控制日志级别。
"""

import logging
import os
import sys


def get_logger(name: str) -> logging.Logger:
    """
    获取统一配置的 Logger 实例

    Args:
        name: 日志名称（通常传 __name__）

    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(f"cortex.{name}")

    # 避免重复添加 handler
    if not logger.handlers:
        level = os.getenv("CORTEX_LOG_LEVEL", "INFO").upper()
        logger.setLevel(getattr(logging, level, logging.INFO))

        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, level, logging.INFO))

        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
