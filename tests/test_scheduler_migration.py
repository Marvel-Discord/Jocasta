"""Tests for the API-driven lifecycle migration (scheduler removal)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import discord

from cogs.polls import PollsCog
from funcs.polls_api_models import Poll


def make_cog():
    class FakeBot:
        def __init__(self):
            self.tasks = {}
            self.tree = MagicMock()
            self.loop = MagicMock()
            self.loop.create_task.side_effect = lambda coro: coro.close()
            self.polls_api = MagicMock()
            self.wait_until_ready = AsyncMock()

    cog = PollsCog(FakeBot())
    cog._home_guild_ids = [100]
    return cog


def make_poll_model(**overrides):
    data = {
        "id": 42,
        "question": "Best hero?",
        "published": True,
        "active": True,
        "guild_id": 100,
        "choices": ["A", "B"],
        "votes": [3, 1],
        "total_votes": 4,
        "time": datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        "start_time": datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        "end_time": datetime(2026, 1, 5, 12, tzinfo=timezone.utc),
        "num": 7,
        "message_id": 555,
        "crosspost_message_ids": [556],
        "tag": 1,
        "image": None,
        "description": None,
        "thread_question": None,
        "show_question": True,
        "show_options": True,
        "show_voting": True,
        "fallback": False,
    }
    data.update(overrides)
    return Poll(**data)


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value):
        self.store[key] = value


async def test_get_end_watermark_defaults_to_24h_lookback():
    cog = make_cog()
    before = discord.utils.utcnow() - timedelta(hours=24)
    got = await cog._get_end_watermark()
    after = discord.utils.utcnow() - timedelta(hours=24)
    assert before <= got <= after


async def test_end_watermark_roundtrips_through_redis():
    cog = make_cog()
    cog.bot.redis = FakeRedis()
    stamp = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    await cog._set_end_watermark(stamp)
    assert await cog._get_end_watermark() == stamp


async def test_end_watermark_falls_back_to_memory_without_redis():
    cog = make_cog()
    stamp = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    await cog._set_end_watermark(stamp)
    assert cog._end_watermark_fallback == stamp
    assert await cog._get_end_watermark() == stamp
