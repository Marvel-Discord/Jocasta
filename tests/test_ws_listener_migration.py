"""Tests for the websocket listener migration."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from cogs.polls import PollsCog
from funcs.polls_api import PollsAPIError
from funcs.polls_api_models import GuildSettings, Poll, Tag, UserVote


def make_cog():
    class FakeBot:
        def __init__(self):
            self.tasks = {"poll_schedules": {"starts": {}, "ends": {}}}
            self.tree = MagicMock()
            self.loop = MagicMock()
            self.loop.create_task.side_effect = lambda coro: coro.close()
            self.polls_api = MagicMock()
            self.wait_until_ready = AsyncMock()

    cog = PollsCog(FakeBot())
    cog.guild_ids = [100]
    cog.pollsme = PollsCog.pollsme._callback.__get__(cog)
    cog.polladminsync = PollsCog.polladminsync._callback.__get__(cog)
    cog.poll_schedule = PollsCog.poll_schedule._callback.__get__(cog)
    cog.poll_start = PollsCog.poll_start._callback.__get__(cog)
    cog.poll_end = PollsCog.poll_end._callback.__get__(cog)
    cog.poll_delete = PollsCog.poll_delete._callback.__get__(cog)
    cog.poll_edit = PollsCog.poll_edit._callback.__get__(cog)
    cog.poll_create = PollsCog.poll_create._callback.__get__(cog)
    cog.poll_bulk_edit = PollsCog.poll_bulk_edit._callback.__get__(cog)
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


def make_tag_dict(**overrides):
    data = {
        "tag": 1,
        "name": "comics",
        "guild_id": 100,
        "channel_id": 300,
        "crosspost_channels": [201],
        "crosspost_servers": [101],
        "current_num": 7,
        "colour": 424242,
        "end_message": None,
        "end_message_latest_ids": [],
        "end_message_replace": False,
        "end_message_role_ids": [],
        "end_message_ping": False,
        "end_message_self_assign": False,
        "persistent": False,
    }
    data.update(overrides)
    return data


def make_guild_dict(**overrides):
    data = {
        "guild_id": 100,
        "default_channel_id": 300,
        "manage_channel_id": [301],
        "manager_role_id": [302],
        "default_colour": 657930,
        "fallback_channel_id": 303,
    }
    data.update(overrides)
    return data


def make_channel(channel_id=300, msg_id=5555):
    channel = MagicMock()
    channel.id = channel_id
    msg = MagicMock()
    msg.id = msg_id
    channel.send = AsyncMock(return_value=msg)
    return channel


async def test_handle_poll_event_deleted_poll_cancels_timers():
    cog = make_cog()
    cog.fetch_poll = AsyncMock(return_value=None)
    task = MagicMock()
    cog.bot.tasks["poll_schedules"]["ends"][42] = task

    await cog.handle_poll_event(42)

    task.cancel.assert_called_once()
    assert 42 not in cog.bot.tasks["poll_schedules"]["ends"]


async def test_handle_poll_event_published_poll_rerenders_and_reschedules():
    cog = make_cog()
    poll_dict = cog.poll_dict(make_poll_model(published=True))
    cog.fetch_poll = AsyncMock(return_value=poll_dict)
    cog.updatepollmessage = AsyncMock()
    cog.update_poll_scheduling = AsyncMock()

    await cog.handle_poll_event(42)

    cog.updatepollmessage.assert_awaited_once_with(poll_dict)
    cog.update_poll_scheduling.assert_awaited_once_with(poll_dict)


async def test_handle_poll_event_unpublished_poll_only_reschedules():
    cog = make_cog()
    poll_dict = cog.poll_dict(make_poll_model(published=False))
    cog.fetch_poll = AsyncMock(return_value=poll_dict)
    cog.updatepollmessage = AsyncMock()
    cog.update_poll_scheduling = AsyncMock()

    await cog.handle_poll_event(42)

    cog.updatepollmessage.assert_not_awaited()
    cog.update_poll_scheduling.assert_awaited_once_with(poll_dict)


async def test_handle_poll_event_skips_foreign_guild():
    cog = make_cog()
    cog.fetch_poll = AsyncMock(return_value=cog.poll_dict(make_poll_model(guild_id=999)))
    cog.updatepollmessage = AsyncMock()
    cog.update_poll_scheduling = AsyncMock()

    await cog.handle_poll_event(42)

    cog.updatepollmessage.assert_not_awaited()
    cog.update_poll_scheduling.assert_not_awaited()


async def test_resync_from_api_runs_the_four_tasks():
    cog = make_cog()
    cog.schedule_starts = AsyncMock()
    cog.schedule_ends = AsyncMock()
    cog.on_startup_buttons = AsyncMock()
    cog.on_startup_self_assign = AsyncMock()

    await cog.resync_from_api()

    cog.schedule_starts.assert_awaited_once()
    cog.schedule_ends.assert_awaited_once()
    cog.on_startup_buttons.assert_awaited_once()
    cog.on_startup_self_assign.assert_awaited_once()


async def test_resync_from_api_routes_the_four_tasks_through_gather(monkeypatch):
    cog = make_cog()

    async def schedule_starts():
        pass

    async def schedule_ends():
        pass

    async def on_startup_buttons():
        pass

    async def on_startup_self_assign():
        pass

    cog.schedule_starts = schedule_starts
    cog.schedule_ends = schedule_ends
    cog.on_startup_buttons = on_startup_buttons
    cog.on_startup_self_assign = on_startup_self_assign

    routed = []

    async def fake_gather(*aws, **kwargs):
        routed.extend(aw.__name__ for aw in aws)
        for aw in aws:
            aw.close()

    monkeypatch.setattr("cogs.polls.asyncio.gather", fake_gather)

    await cog.resync_from_api()

    assert routed == [
        "schedule_starts",
        "schedule_ends",
        "on_startup_buttons",
        "on_startup_self_assign",
    ]


def test_init_creates_ws_client_with_unified_handler():
    cog = make_cog()
    assert cog.poll_ws_client is not None
    assert cog.poll_ws_client.on_poll_update == cog.handle_poll_event
    assert cog.poll_ws_client.on_full_resync == cog.resync_from_api


async def test_stop_ws_listener_cancels_task_and_stops_client():
    cog = make_cog()
    cog.poll_ws_client = MagicMock()
    cog.poll_ws_client.stop = AsyncMock()
    cog.poll_ws_task = MagicMock()

    await cog._stop_ws_listener()

    cog.poll_ws_task.cancel.assert_called_once()
    cog.poll_ws_client.stop.assert_awaited_once()


def test_cog_unload_schedules_stop():
    cog = make_cog()
    cog._stop_ws_listener = AsyncMock()

    cog.cog_unload()

    cog._stop_ws_listener.assert_not_awaited()  # scheduled, not awaited inline
