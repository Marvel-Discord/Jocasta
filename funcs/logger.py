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

# stdlib loggers whose records flow through the bridge. All pinned at
# INFO regardless of LOG_LEVEL: LOG_LEVEL=DEBUG means OUR detail, not
# third-party per-request/payload firehose (discord.http/gateway would
# be the worst offenders; redis pool chatter and the rest follow).
BRIDGED_LOGGERS = [
    "discord",
    "discord.http",
    "discord.gateway",
    "websockets",
    "aiohttp",
    "redis",
    "asyncio",
]

# third-party loggers that would otherwise gain per-request INFO lines
# through the bridge (they were silently dropped pre-loguru); WARNING+
# still surfaces real failures
QUIET_LOGGERS = [
    "httpx2",
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
    # Root gate at INFO: unknown third-party stdlib loggers stay quiet at
    # dev DEBUG; the bridge still forwards INFO+ records to the sink,
    # which applies the real level (LOG_LEVEL).
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)
    for name in BRIDGED_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

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
