"""Tests for funcs/redis.py — the Redis connection cog."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from funcs.redis import RedisCog


@pytest.mark.asyncio
async def test_cog_load_connects_and_exposes_bot_redis(fake_redis):
    """On cog_load, bot.redis should be a connected client."""
    bot = MagicMock()
    bot.redis = None
    cog = RedisCog(bot)

    with patch("funcs.redis.redis.from_url", return_value=fake_redis):
        await cog.cog_load()

    assert bot.redis is fake_redis
    # The client should actually work
    await bot.redis.set("test:key", "value")
    assert await bot.redis.get("test:key") == "value"


@pytest.mark.asyncio
async def test_cog_load_sets_bot_redis_none_on_failure():
    """If Redis is unreachable, bot.redis should be None (graceful degradation)."""
    bot = MagicMock()
    bot.redis = None
    cog = RedisCog(bot)

    failing_client = AsyncMock()
    failing_client.ping.side_effect = ConnectionError("Redis refused")
    with patch("funcs.redis.redis.from_url", return_value=failing_client):
        await cog.cog_load()

    assert bot.redis is None


@pytest.mark.asyncio
async def test_cog_unload_closes_client(fake_redis):
    """Cog unload should close the Redis connection."""
    bot = MagicMock()
    bot.redis = fake_redis
    cog = RedisCog(bot)

    with patch.object(fake_redis, "aclose", new=AsyncMock()) as mock_close:
        await cog.cog_unload()
        mock_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cog_unload_handles_none_redis():
    """Unload should be a no-op if bot.redis is None."""
    bot = MagicMock()
    bot.redis = None
    cog = RedisCog(bot)

    # Should not raise
    await cog.cog_unload()
