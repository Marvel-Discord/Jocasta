"""Tests for the API-driven lifecycle migration (scheduler removal)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

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
    poll = cog.poll_dict(
        make_poll_model(
            published=False,
            message_id=None,
            start_time=discord.utils.utcnow() - timedelta(hours=1),
            end_time=None,
        )
    )
    cog.fetch_poll = AsyncMock(return_value=poll)
    cog.split_start_polls = AsyncMock(return_value=True)
    cog.finalize_ended_poll = AsyncMock()

    assert await cog.render_pending_poll(42) is True
    cog.split_start_polls.assert_awaited_once_with(42, natural=True)
    cog.finalize_ended_poll.assert_not_awaited()


async def test_render_pending_poll_finalizes_poll_ended_during_downtime():
    cog = make_cog()
    started = discord.utils.utcnow() - timedelta(hours=2)
    ended = discord.utils.utcnow() - timedelta(hours=1)
    pre_render = cog.poll_dict(
        make_poll_model(
            published=False,
            message_id=None,
            active=False,
            start_time=started,
            end_time=ended,
        )
    )
    post_render = cog.poll_dict(
        make_poll_model(
            published=True,
            message_id=777,
            active=False,
            start_time=started,
            end_time=ended,
        )
    )
    cog.fetch_poll = AsyncMock(side_effect=[pre_render, post_render])
    cog.split_start_polls = AsyncMock(return_value=True)
    cog.finalize_ended_poll = AsyncMock()

    assert await cog.render_pending_poll(42) is True
    cog.finalize_ended_poll.assert_awaited_once_with(post_render)


async def test_render_pending_poll_skips_already_rendered():
    cog = make_cog()
    cog.fetch_poll = AsyncMock(return_value=cog.poll_dict(make_poll_model()))
    cog.split_start_polls = AsyncMock(return_value=True)

    assert await cog.render_pending_poll(42) is False
    cog.split_start_polls.assert_not_awaited()


async def test_render_pending_poll_skips_future_start():
    cog = make_cog()
    poll = cog.poll_dict(
        make_poll_model(
            published=False,
            message_id=None,
            start_time=discord.utils.utcnow() + timedelta(hours=1),
        )
    )
    cog.fetch_poll = AsyncMock(return_value=poll)
    cog.split_start_polls = AsyncMock(return_value=True)

    assert await cog.render_pending_poll(42) is False
    cog.split_start_polls.assert_not_awaited()


async def test_render_pending_poll_skips_unstarted():
    cog = make_cog()
    poll = cog.poll_dict(
        make_poll_model(published=False, message_id=None, start_time=None)
    )
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


async def test_process_missed_ends_watermark_snapshots_before_query():
    cog = make_cog()
    cog.bot.redis = FakeRedis()
    query_time = {}

    async def sync_and_stamp(*args, **kwargs):
        query_time["at"] = discord.utils.utcnow()
        return []

    cog.bot.polls_api.sync_all_polls = AsyncMock(side_effect=sync_and_stamp)

    await cog.process_missed_ends()

    stored = await cog._get_end_watermark()
    assert stored <= query_time["at"]


async def test_process_missed_ends_exception_leaves_watermark_unadvanced():
    cog = make_cog()
    cog.bot.redis = FakeRedis()
    initial = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    await cog._set_end_watermark(initial)
    cog.bot.polls_api.sync_all_polls = AsyncMock(
        return_value=[make_poll_model(active=False)]
    )
    cog.finalize_ended_poll = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await cog.process_missed_ends()

    assert await cog._get_end_watermark() == initial


async def test_start_polls_skips_in_flight_renders():
    cog = make_cog()
    cog.bot.rendering_polls.add(42)
    cog.fetch_poll = AsyncMock()

    result = await cog.start_polls([42])

    assert result is None
    cog.fetch_poll.assert_not_awaited()


def make_thread(thread_id=555, archived=False):
    thread = MagicMock()
    thread.id = thread_id
    thread.edit = AsyncMock()
    return thread


def make_finalize_env():
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
    cog.bot.get_channel = MagicMock(return_value=channel)
    thread = make_thread(poll["message_id"])
    guild = MagicMock()
    guild.get_channel_or_thread = MagicMock(
        side_effect=lambda cid: thread if cid == poll["message_id"] else None
    )
    cog.bot.get_guild = MagicMock(return_value=guild)
    cog.update_poll_message = AsyncMock()
    return cog, poll, thread


async def test_finalize_ended_poll_archives_threads_and_rerenders():
    cog, poll, thread = make_finalize_env()

    await cog.finalize_ended_poll(poll)

    thread.edit.assert_awaited_once_with(archived=True, locked=True)
    cog.update_poll_message.assert_awaited_once_with(poll)


async def test_finalize_ended_poll_is_idempotent():
    cog, poll, thread = make_finalize_env()

    await cog.finalize_ended_poll(poll)
    await cog.finalize_ended_poll(poll)

    assert cog.update_poll_message.await_count == 2
    assert thread.edit.await_count == 2


async def test_finalize_ended_poll_aborts_when_guild_fetch_fails():
    cog = make_cog()
    poll = cog.poll_dict(make_poll_model(active=False))
    cog.fetch_tag = AsyncMock(return_value=None)
    cog.fetch_guild_info = AsyncMock(return_value=None)
    cog.update_poll_message = AsyncMock()

    await cog.finalize_ended_poll(poll)

    cog.update_poll_message.assert_not_awaited()


async def test_start_polls_holds_render_guard_through_render():
    cog = make_cog()
    poll = cog.poll_dict(make_poll_model())
    observed = []

    async def fetch_and_observe(poll_id):
        observed.append(poll_id in cog.bot.rendering_polls)
        return poll

    cog.fetch_poll = AsyncMock(side_effect=fetch_and_observe)
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
    cog.format_poll_message = AsyncMock(
        return_value={"content": None, "embed": None, "view": None}
    )
    cog.update_poll_message = AsyncMock()
    cog.bot.polls_api.publish_poll = AsyncMock()
    channel = MagicMock()
    msg = MagicMock()
    channel.send = AsyncMock(return_value=msg)
    cog.bot.get_channel = MagicMock(return_value=channel)

    final = await cog.start_polls([42])

    assert final is not None
    assert len(final) == 1
    assert observed and all(observed)
    assert cog.bot.rendering_polls == set()


async def test_start_polls_releases_render_guard_on_error():
    cog = make_cog()

    async def fetch_and_observe(poll_id):
        assert 42 in cog.bot.rendering_polls
        raise RuntimeError("boom")

    cog.fetch_poll = AsyncMock(side_effect=fetch_and_observe)

    with pytest.raises(RuntimeError):
        await cog.start_polls([42])

    assert cog.bot.rendering_polls == set()


async def test_handle_poll_event_renders_pending_start():
    cog = make_cog()
    poll = cog.poll_dict(
        make_poll_model(
            published=False,
            message_id=None,
            start_time=discord.utils.utcnow() - timedelta(hours=1),
            end_time=None,
        )
    )
    cog.fetch_poll = AsyncMock(return_value=poll)
    cog.render_pending_poll = AsyncMock(return_value=True)
    cog.update_poll_message = AsyncMock()

    await cog.handle_poll_event(42)

    cog.render_pending_poll.assert_awaited_once_with(42)
    cog.update_poll_message.assert_not_awaited()


async def test_handle_poll_event_renders_before_finalize_when_both_due():
    cog = make_cog()
    now = discord.utils.utcnow()
    poll = cog.poll_dict(
        make_poll_model(
            published=False,
            message_id=None,
            active=False,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
        )
    )
    cog.fetch_poll = AsyncMock(return_value=poll)
    cog.render_pending_poll = AsyncMock(return_value=True)
    cog.finalize_ended_poll = AsyncMock()
    cog.update_poll_message = AsyncMock()

    await cog.handle_poll_event(42)

    cog.render_pending_poll.assert_awaited_once_with(42)
    cog.finalize_ended_poll.assert_not_awaited()


async def test_handle_poll_event_finalizes_ended_poll():
    cog = make_cog()
    poll = cog.poll_dict(
        make_poll_model(active=False, end_time=datetime(2026, 1, 5, 12, tzinfo=timezone.utc))
    )
    cog.fetch_poll = AsyncMock(return_value=poll)
    cog.finalize_ended_poll = AsyncMock()
    cog.update_poll_message = AsyncMock()

    await cog.handle_poll_event(42)

    cog.finalize_ended_poll.assert_awaited_once_with(poll)
    cog.update_poll_message.assert_not_awaited()


async def test_handle_poll_event_rerenders_running_poll():
    cog = make_cog()
    poll = cog.poll_dict(make_poll_model())
    cog.fetch_poll = AsyncMock(return_value=poll)
    cog.render_pending_poll = AsyncMock()
    cog.finalize_ended_poll = AsyncMock()
    cog.update_poll_message = AsyncMock()

    await cog.handle_poll_event(42)

    cog.update_poll_message.assert_awaited_once_with(poll)
    cog.render_pending_poll.assert_not_awaited()
    cog.finalize_ended_poll.assert_not_awaited()


async def test_handle_poll_event_deleted_poll_is_a_no_op():
    cog = make_cog()
    cog.fetch_poll = AsyncMock(return_value=None)
    cog.render_pending_poll = AsyncMock()
    cog.finalize_ended_poll = AsyncMock()
    cog.update_poll_message = AsyncMock()

    await cog.handle_poll_event(42)

    cog.render_pending_poll.assert_not_awaited()
    cog.finalize_ended_poll.assert_not_awaited()
    cog.update_poll_message.assert_not_awaited()


async def test_handle_poll_event_skips_foreign_guild():
    cog = make_cog()
    cog.fetch_poll = AsyncMock(
        return_value=cog.poll_dict(make_poll_model(guild_id=999))
    )
    cog.render_pending_poll = AsyncMock()
    cog.update_poll_message = AsyncMock()

    await cog.handle_poll_event(42)

    cog.render_pending_poll.assert_not_awaited()
    cog.update_poll_message.assert_not_awaited()


async def test_end_poll_manual_writes_end_time_then_finalizes():
    cog = make_cog()
    poll = cog.poll_dict(make_poll_model())
    cog.fetch_poll = AsyncMock(return_value=poll)
    cog.finalize_ended_poll = AsyncMock()
    cog.bot.polls_api.update_polls = AsyncMock()

    await cog.end_poll(42, user_id=1)

    body = cog.bot.polls_api.update_polls.call_args[0][0][0]
    assert body["id"] == 42
    assert "end_time" in body
    cog.finalize_ended_poll.assert_awaited_once()


async def test_end_poll_skips_inactive_poll():
    cog = make_cog()
    cog.fetch_poll = AsyncMock(
        return_value=cog.poll_dict(make_poll_model(active=False))
    )
    cog.bot.polls_api.update_polls = AsyncMock()
    cog.finalize_ended_poll = AsyncMock()

    await cog.end_poll(42)

    cog.bot.polls_api.update_polls.assert_not_awaited()
    cog.finalize_ended_poll.assert_not_awaited()


async def test_resync_runs_renders_ends_and_views():
    cog = make_cog()
    cog.process_pending_renders = AsyncMock()
    cog.process_missed_ends = AsyncMock()
    cog.on_startup_buttons = AsyncMock()
    cog.on_startup_self_assign = AsyncMock()

    await cog.resync_from_api()

    cog.process_pending_renders.assert_awaited_once()
    cog.process_missed_ends.assert_awaited_once()
    cog.on_startup_buttons.assert_awaited_once()
    cog.on_startup_self_assign.assert_awaited_once()


def test_scheduler_machinery_is_gone():
    cog = make_cog()
    assert not hasattr(cog, "scheduler")
    assert not hasattr(cog, "schedule_starts")
    assert not hasattr(cog, "schedule_ends")
    assert not hasattr(cog, "update_poll_scheduling")
    assert "poll_schedules" not in cog.bot.tasks
