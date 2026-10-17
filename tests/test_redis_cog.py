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
    """If Redis is unreachable on every attempt, bot.redis should be None
    (graceful degradation). Backoff sleeps are patched out."""
    bot = MagicMock()
    bot.redis = None
    cog = RedisCog(bot)

    def failing_client(*_args, **_kwargs):
        client = AsyncMock()
        client.ping.side_effect = ConnectionError("Redis refused")
        return client

    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    with (
        patch("funcs.redis.redis.from_url", side_effect=failing_client),
        patch("funcs.redis.asyncio.sleep", new=fake_sleep),
    ):
        await cog.cog_load()

    assert bot.redis is None
    assert len(sleeps) == 4  # one backoff between each of the 5 attempts
    assert sleeps == [1.0, 2.0, 4.0, 8.0]


@pytest.mark.asyncio
async def test_cog_load_retries_until_redis_comes_up():
    """A Redis that is down at boot but recovers mid-retry must end
    connected — the boot-retry hardening's whole point."""
    bot = MagicMock()
    bot.redis = None
    cog = RedisCog(bot)

    attempts = {"n": 0}

    def flaky_client(*_args, **_kwargs):
        attempts["n"] += 1
        client = AsyncMock()
        if attempts["n"] < 3:
            client.ping.side_effect = ConnectionError("Redis starting up")
        client.aclose = AsyncMock()
        return client

    async def fake_sleep(delay):
        return None

    with (
        patch("funcs.redis.redis.from_url", side_effect=flaky_client),
        patch("funcs.redis.asyncio.sleep", new=fake_sleep),
    ):
        await cog.cog_load()

    assert bot.redis is not None
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_cog_load_passes_socket_connect_timeout(fake_redis):
    """The connection must carry a connect timeout so boot retries are
    bounded rather than hanging on an unresponsive host."""
    bot = MagicMock()
    bot.redis = None
    cog = RedisCog(bot)

    with patch(
        "funcs.redis.redis.from_url", return_value=fake_redis
    ) as mock_from_url:
        await cog.cog_load()

    assert mock_from_url.call_args.kwargs["socket_connect_timeout"] == 5


@pytest.mark.asyncio
async def test_cog_load_closes_failed_clients():
    """Each failed attempt closes its client — no leaked connections
    across retries."""
    bot = MagicMock()
    bot.redis = None
    cog = RedisCog(bot)

    clients = []

    def failing_client(*_args, **_kwargs):
        client = AsyncMock()
        client.ping.side_effect = ConnectionError("Redis refused")
        client.aclose = AsyncMock()
        clients.append(client)
        return client

    async def fake_sleep(delay):
        return None

    with (
        patch("funcs.redis.redis.from_url", side_effect=failing_client),
        patch("funcs.redis.asyncio.sleep", new=fake_sleep),
    ):
        await cog.cog_load()

    assert bot.redis is None
    for client in clients:
        client.aclose.assert_awaited_once()


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
