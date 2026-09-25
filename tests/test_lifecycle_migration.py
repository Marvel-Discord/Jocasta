"""Tests for the lifecycle migration from postgres to the polls API."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from cogs.polls import PollsCog
from funcs.polls_api_models import GuildSettings, Poll, Tag, UserVote


def make_cog():
    class FakeBot:
        def __init__(self):
            self.tasks = {}
            self.tree = MagicMock()
            self.loop = MagicMock()
            self.loop.create_task.side_effect = lambda coro: coro.close()
            self.polls_api = MagicMock()

    cog = PollsCog(FakeBot())
    cog.guild_ids = [288896937074360321]
    cog.pollsme = PollsCog.pollsme._callback.__get__(cog)
    cog.polladminsync = PollsCog.polladminsync._callback.__get__(cog)
    cog.poll_schedule = PollsCog.poll_schedule._callback.__get__(cog)
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
        "channel_id": 200,
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


async def test_poll_schedule_writes_start_time_via_update_polls():
    cog = make_cog()
    poll = make_poll_model(published=False, start_time=None, end_time=None, time=None)
    cog.fetch_poll = AsyncMock(return_value=cog.poll_dict(poll))
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.schedule_starts = AsyncMock()
    cog.fetchcolourbyid = AsyncMock(return_value=1)
    cog.bot.polls_api.update_polls = AsyncMock(return_value=[poll])

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.channel_id = 301
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_schedule(interaction, 42, schedule_time=1893456000)

    cog.bot.polls_api.update_polls.assert_awaited_once()
    body = cog.bot.polls_api.update_polls.await_args.args[0]
    assert body[0]["id"] == 42
    assert body[0]["question"] == "Best hero?"
    assert body[0]["choices"] == ["A", "B"]
    assert body[0]["start_time"] == "2030-01-01T00:00:00+00:00"
    assert cog.bot.polls_api.update_polls.await_args.args[1] == 1234
    cog.schedule_starts.assert_awaited_once()


async def test_poll_schedule_clear_schedule_sends_null_start_time():
    cog = make_cog()
    poll = make_poll_model(published=False)
    cog.fetch_poll = AsyncMock(return_value=cog.poll_dict(poll))
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.schedule_starts = AsyncMock()
    cog.fetchcolourbyid = AsyncMock(return_value=1)
    cog.bot.polls_api.update_polls = AsyncMock(return_value=[poll])

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_schedule(interaction, 42, schedule_time=-1)

    body = cog.bot.polls_api.update_polls.await_args.args[0]
    assert body[0]["start_time"] is None


async def test_poll_schedule_duration_computes_end_time():
    cog = make_cog()
    poll = make_poll_model(
        published=False,
        time=datetime(2030, 1, 1, tzinfo=timezone.utc),
        start_time=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    cog.fetch_poll = AsyncMock(return_value=cog.poll_dict(poll))
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.schedule_starts = AsyncMock()
    cog.schedule_ends = AsyncMock()
    cog.fetchcolourbyid = AsyncMock(return_value=1)
    cog.bot.polls_api.update_polls = AsyncMock(return_value=[poll])

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_schedule(interaction, 42, duration=3600)

    calls = cog.bot.polls_api.update_polls.await_args_list
    end_body = calls[-1].args[0][0]
    assert "end_time" in end_body
    assert end_body["end_time"] == "2030-01-01T01:00:00+00:00"
    assert end_body["id"] == 42


async def test_poll_schedule_duration_published_uses_now_plus_duration():
    cog = make_cog()
    poll = make_poll_model(published=True)
    cog.fetch_poll = AsyncMock(return_value=cog.poll_dict(poll))
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.schedule_starts = AsyncMock()
    cog.schedule_ends = AsyncMock()
    cog.fetchcolourbyid = AsyncMock(return_value=1)
    cog.bot.polls_api.update_polls = AsyncMock(return_value=[poll])

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_schedule(interaction, 42, duration=3600)

    calls = cog.bot.polls_api.update_polls.await_args_list
    end_body = calls[-1].args[0][0]
    assert "end_time" in end_body
    parsed = datetime.fromisoformat(end_body["end_time"])
    delta = parsed - datetime.now(timezone.utc)
    assert timedelta(hours=1) > delta > timedelta(minutes=59)
    assert end_body["id"] == 42


async def test_poll_schedule_duration_clear_sends_null_end_time():
    cog = make_cog()
    poll = make_poll_model(
        published=False,
        time=datetime(2030, 1, 1, tzinfo=timezone.utc),
        start_time=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    cog.fetch_poll = AsyncMock(return_value=cog.poll_dict(poll))
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.schedule_starts = AsyncMock()
    cog.schedule_ends = AsyncMock()
    cog.fetchcolourbyid = AsyncMock(return_value=1)
    cog.bot.polls_api.update_polls = AsyncMock(return_value=[poll])

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_schedule(interaction, 42, duration=-1)

    calls = cog.bot.polls_api.update_polls.await_args_list
    end_body = calls[-1].args[0][0]
    assert "end_time" in end_body
    assert end_body["end_time"] is None
    assert end_body["id"] == 42
