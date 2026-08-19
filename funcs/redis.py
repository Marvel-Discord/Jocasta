import redis.asyncio as redis
from discord.ext import commands

from config import *


class RedisCog(commands.Cog, name="Redis"):
    """Manages the bot's Redis connection and exposes it as `bot.redis`.

    On failure to connect, `bot.redis` is set to None — cogs that use it
    must handle this case (graceful degradation).
    """

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.redis = redis.from_url(redis_url, decode_responses=True)
        try:
            await self.bot.redis.ping()
            print("Connected to Redis")
        except Exception as e:
            print(f"Failed to connect to Redis: {e}")
            self.bot.redis = None

    async def cog_unload(self):
        if self.bot.redis:
            await self.bot.redis.aclose()


async def setup(bot):
    await bot.add_cog(RedisCog(bot))
