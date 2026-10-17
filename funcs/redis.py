import asyncio

import redis.asyncio as redis
from discord.ext import commands
from loguru import logger

from config import *

REDIS_CONNECT_ATTEMPTS = 5
REDIS_BACKOFF_INITIAL = 1.0
REDIS_BACKOFF_MAX = 16.0
REDIS_SOCKET_CONNECT_TIMEOUT = 5


class RedisCog(commands.Cog, name="Redis"):
    """Manages the bot's Redis connection and exposes it as `bot.redis`.

    Retries the connection with exponential backoff at boot (Redis being
    briefly unavailable at start otherwise degraded news-ping tracking
    until restart). On final failure, `bot.redis` is set to None — cogs
    that use it must handle this case (graceful degradation).
    """

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        backoff = REDIS_BACKOFF_INITIAL
        for attempt in range(1, REDIS_CONNECT_ATTEMPTS + 1):
            client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=REDIS_SOCKET_CONNECT_TIMEOUT,
            )
            try:
                await client.ping()
                logger.info("connected to redis")
                self.bot.redis = client
                return
            except Exception as e:
                await client.aclose()
                if attempt == REDIS_CONNECT_ATTEMPTS:
                    logger.error(
                        "failed to connect to redis after {} attempts: {}",
                        attempt,
                        e,
                    )
                    self.bot.redis = None
                    return
                logger.warning(
                    "redis connect attempt {}/{} failed: {} - retrying in {}s",
                    attempt,
                    REDIS_CONNECT_ATTEMPTS,
                    e,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, REDIS_BACKOFF_MAX)

    async def cog_unload(self):
        if self.bot.redis:
            await self.bot.redis.aclose()


async def setup(bot):
    await bot.add_cog(RedisCog(bot))
