"""Tests for the read-path migration from postgres to the polls API."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from cogs.polls import PollsCog
from funcs.polls_api_models import GuildSettings, Poll, Tag


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


async def test_polldict_synthesizes_duration_and_merges_tag_guild():
    cog = make_cog()
    d = cog.polldict(make_poll_model(), make_tag_dict(), make_guild_dict())
    assert d["duration"] == timedelta(days=4)
    assert d["channel_id"] == 200
    assert d["persistent"] is False
    assert d["default_channel_id"] == 300
    assert d["fallback_channel_id"] == 303
    assert d["time"] == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    assert d["votes"] == [3, 1]
    assert d["active"] is True


async def test_polldict_missing_times_gives_none_duration():
    cog = make_cog()
    d = cog.polldict(make_poll_model(start_time=None, end_time=None, time=None))
    assert d["duration"] is None


async def test_fetchallpolls_composes_join_shape_and_filters_published():
    cog = make_cog()
    cog.bot.polls_api.sync_all_polls = AsyncMock(
        return_value=[make_poll_model(id=1), make_poll_model(id=2, published=False)]
    )
    cog.bot.polls_api.get_guild = AsyncMock(return_value=GuildSettings(**make_guild_dict()))
    cog.bot.polls_api.get_tags = AsyncMock(return_value=[Tag(**make_tag_dict())])

    published_only = await cog.fetchallpolls()
    assert [p["id"] for p in published_only] == [1]
    assert published_only[0]["name"] == "comics"

    everything = await cog.fetchallpolls(showunpublished=True)
    assert [p["id"] for p in everything] == [1, 2]
    cog.bot.polls_api.sync_all_polls.assert_awaited_with(guildId=288896937074360321)


def test_polls_guild_id_prefers_guild_ids_attr():
    cog = make_cog()
    assert cog.polls_guild_id() == 288896937074360321
    cog.guild_ids = None
    cog.bot.guilds = [MagicMock(id=999)]
    assert cog.polls_guild_id() == 999
