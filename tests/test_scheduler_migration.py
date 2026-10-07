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


async def test_render_pending_poll_renders_started_unrendered_poll():
    cog = make_cog()
    poll = cog.poll_dict(make_poll_model(message_id=None))
    cog.fetch_poll = AsyncMock(return_value=poll)
    cog.split_start_polls = AsyncMock(return_value=True)

    assert await cog.render_pending_poll(42) is True
    cog.split_start_polls.assert_awaited_once_with(42, natural=True)


async def test_render_pending_poll_skips_already_rendered():
    cog = make_cog()
    cog.fetch_poll = AsyncMock(return_value=cog.poll_dict(make_poll_model()))
    cog.split_start_polls = AsyncMock(return_value=True)

    assert await cog.render_pending_poll(42) is False
    cog.split_start_polls.assert_not_awaited()


async def test_render_pending_poll_skips_unpublished():
    cog = make_cog()
    poll = cog.poll_dict(make_poll_model(published=False, message_id=None))
    cog.fetch_poll = AsyncMock(return_value=poll)
    cog.split_start_polls = AsyncMock(return_value=True)

    assert await cog.render_pending_poll(42) is False
    cog.split_start_polls.assert_not_awaited()


async def test_render_pending_poll_skips_missing_poll():
    cog = make_cog()
    cog.fetch_poll = AsyncMock(return_value=None)
    cog.split_start_polls = AsyncMock(return_value=True)

    assert await cog.render_pending_poll(42) is False
    cog.split_start_polls.assert_not_awaited()


async def test_process_pending_renders_queries_and_renders():
    cog = make_cog()
    cog.bot.polls_api.sync_all_polls = AsyncMock(
        return_value=[make_poll_model(id=42, message_id=None)]
    )
    cog.render_pending_poll = AsyncMock(return_value=True)

    await cog.process_pending_renders()

    cog.bot.polls_api.sync_all_polls.assert_awaited_once_with(
        100, pending_render=True
    )
    cog.render_pending_poll.assert_awaited_once_with(42)


async def test_process_missed_ends_finalizes_and_advances_watermark():
    cog = make_cog()
    cog.bot.redis = FakeRedis()
    ended = make_poll_model(active=False)
    cog.bot.polls_api.sync_all_polls = AsyncMock(return_value=[ended])
    cog.finalize_ended_poll = AsyncMock()
    before = discord.utils.utcnow()

    await cog.process_missed_ends()

    cog.bot.polls_api.sync_all_polls.assert_awaited_once()
    kwargs = cog.bot.polls_api.sync_all_polls.call_args[1]
    assert kwargs["ended_since"] is not None
    cog.finalize_ended_poll.assert_awaited_once_with(cog.poll_dict(ended))
    stored = await cog._get_end_watermark()
    assert stored >= before


async def test_start_polls_skips_in_flight_renders():
    cog = make_cog()
    cog._rendering.add(42)
    cog.fetch_poll = AsyncMock()

    result = await cog.start_polls([42])

    assert result is None
    cog.fetch_poll.assert_not_awaited()


def make_thread(thread_id=555, archived=False):
    thread = MagicMock()
    thread.id = thread_id
    thread.edit = AsyncMock()
    return thread


async def test_finalize_ended_poll_archives_threads_and_rerenders():
    cog = make_cog()
    poll = cog.poll_dict(
        make_poll_model(active=False, thread_question="Discuss!")
    )
    cog.fetch_tag = AsyncMock(return_value=None)
    cog.fetch_guild_info = AsyncMock(
        return_value={
            "guild_id": 100,
            "default_channel_id": 300,
            "manage_channel_id": [301],
            "manager_role_id": [302],
            "default_colour": None,
            "fallback_channel_id": 303,
        }
    )
    channel = MagicMock()
    channel.guild = MagicMock()
    channel.guild.get_channel_or_thread = MagicMock(return_value=None)
    cog.bot.get_channel = MagicMock(return_value=channel)
    cog.bot.get_guild = MagicMock(return_value=MagicMock())
    cog.update_poll_message = AsyncMock()

    await cog.finalize_ended_poll(poll)

    cog.update_poll_message.assert_awaited_once_with(poll)


async def test_finalize_ended_poll_aborts_when_guild_fetch_fails():
    cog = make_cog()
    poll = cog.poll_dict(make_poll_model(active=False))
    cog.fetch_tag = AsyncMock(return_value=None)
    cog.fetch_guild_info = AsyncMock(return_value=None)
    cog.update_poll_message = AsyncMock()

    await cog.finalize_ended_poll(poll)

    cog.update_poll_message.assert_not_awaited()
