"""
VRC-VideoTools - 日志管理模块
提供统一的控制台与文件双重日志输出，方便调试与问题排查
"""

from __future__ import annotations
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional


LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
LOG_FILE = os.path.join(LOG_DIR, "vrc_videotools.log")


class SafeStreamHandler(logging.StreamHandler):
    """确保在 Windows GBK 控制台下也能安全输出任意 Unicode/Emoji 字符的 StreamHandler"""
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            stream.write(msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)


def setup_logger(
    level: int = logging.DEBUG,
    log_to_file: bool = True,
    log_to_console: bool = True
) -> logging.Logger:
    """
    初始化全局日志记录器
    :param level: 日志级别，默认 DEBUG 详细日志
    :param log_to_file: 是否输出到 logs/vrc_videotools.log
    :param log_to_console: 是否输出到终端控制台
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 避免重复添加 Handler
    if root_logger.handlers:
        root_logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. 终端控制台输出
    if log_to_console:
        console_handler = SafeStreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # 2. 本地文件滚动输出 (最大 10MB，保留 3 个备份)
    if log_to_file:
        file_handler = RotatingFileHandler(
            filename=LOG_FILE,
            maxBytes=10 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # 降低第三方库 noisy 日志
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)

    logger = logging.getLogger("VRC-VideoTools")
    logger.info("=" * 60)
    logger.info("VRC-VideoTools 日志系统初始化完成 (日志级别: DEBUG)")
    logger.info(f"本地日志持久化文件: {LOG_FILE}")
    logger.info("=" * 60)
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """获取指定模块命名的 Logger"""
    if name:
        return logging.getLogger(f"VRC-VideoTools.{name}")
    return logging.getLogger("VRC-VideoTools")
