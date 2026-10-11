"""Loguru configuration: single stderr sink, LOG_LEVEL env, stdlib bridge.

Import once from main.py (before cogs load). Third-party stdlib loggers are
capped at INFO so LOG_LEVEL=DEBUG means OUR detail, not discord.py's
per-request firehose.
"""
import inspect
import logging
import os
import sys

from loguru import logger

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# stdlib loggers whose records should flow through the bridge
BRIDGED_LOGGERS = [
    "discord",
    "websockets",
    "aiohttp",
    "redis",
    "asyncio",
]

# capped at INFO regardless of LOG_LEVEL (per-request/payload flood)
CAPPED_LOGGERS = [
    "discord.http",
    "discord.gateway",
]


class InterceptHandler(logging.Handler):
    """Routes stdlib logging records into loguru (the documented recipe)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup() -> None:
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in BRIDGED_LOGGERS:
        logging.getLogger(name).setLevel(logging.DEBUG)
    # cap the noisy ones explicitly (they inherit from "discord" otherwise)
    for name in CAPPED_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)

    logger.remove()
    logger.add(
        sys.stderr,
        level=LOG_LEVEL,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )


setup()
