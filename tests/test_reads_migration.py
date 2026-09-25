"""Tests for the read-path migration from postgres to the polls API."""
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


from funcs.polls_api import PollsAPIError


async def test_fetchpoll_returns_none_on_404():
    cog = make_cog()
    cog.bot.polls_api.get_poll = AsyncMock(side_effect=PollsAPIError(404, "not found"))
    cog.fetchtag = AsyncMock(return_value=None)
    cog.fetchguildinfo = AsyncMock(return_value=None)
    assert await cog.fetchpoll(42) is None


async def test_fetchpoll_composes_poll_tag_guild():
    cog = make_cog()
    cog.bot.polls_api.get_poll = AsyncMock(return_value=make_poll_model())
    cog.fetchtag = AsyncMock(return_value=make_tag_dict())
    cog.fetchguildinfo = AsyncMock(return_value=make_guild_dict())
    poll = await cog.fetchpoll(42)
    assert poll["id"] == 42
    assert poll["name"] == "comics"
    assert poll["default_channel_id"] == 300
    cog.bot.polls_api.get_poll.assert_awaited_once_with(42)


async def test_fetchguildinfo_returns_dict_or_none_on_404():
    cog = make_cog()
    cog.bot.polls_api.get_guild = AsyncMock(return_value=GuildSettings(**make_guild_dict()))
    assert (await cog.fetchguildinfo(100))["default_channel_id"] == 300
    cog.bot.polls_api.get_guild = AsyncMock(side_effect=PollsAPIError(404, "nope"))
    assert await cog.fetchguildinfo(100) is None


async def test_fetchguildinfobymanagechannel_checks_home_guild_array():
    cog = make_cog()
    cog.bot.polls_api.get_guild = AsyncMock(return_value=GuildSettings(**make_guild_dict()))
    assert (await cog.fetchguildinfobymanagechannel(301))["guild_id"] == 100
    assert await cog.fetchguildinfobymanagechannel(999) is None


async def test_fetchtag_returns_dict_none_on_falsy_and_404():
    cog = make_cog()
    cog.bot.polls_api.get_tag = AsyncMock(return_value=Tag(**make_tag_dict()))
    assert (await cog.fetchtag(1))["name"] == "comics"
    cog.bot.polls_api.get_tag = AsyncMock(side_effect=PollsAPIError(404, "nope"))
    assert await cog.fetchtag(1) is None
    cog.bot.polls_api.get_tag = AsyncMock(return_value=Tag(**make_tag_dict()))
    assert await cog.fetchtag(0) is None
    cog.bot.polls_api.get_tag.assert_not_awaited()


async def test_fetchalltags_and_fetchtagsbyguildid_filter_client_side():
    cog = make_cog()
    cog.bot.polls_api.get_tags = AsyncMock(
        return_value=[Tag(**make_tag_dict()), Tag(**make_tag_dict(tag=2, guild_id=100))]
    )
    assert len(await cog.fetchalltags()) == 2
    cog.bot.polls_api.get_tags = AsyncMock(
        return_value=[Tag(**make_tag_dict()), Tag(**make_tag_dict(tag=2, guild_id=777))]
    )
    assert [t["tag"] for t in await cog.fetchtagsbyguildid(100)] == [1]


async def test_searchpollsbyid_prefix_filters_over_full_fetch():
    cog = make_cog()
    cog.fetchallpolls = AsyncMock(
        return_value=[{"id": 12340, "published": True}, {"id": 12399, "published": False}, {"id": 55555, "published": True}]
    )
    assert [p["id"] for p in await cog.searchpollsbyid(123)] == [12340]
    assert [p["id"] for p in await cog.searchpollsbyid(123, showunpublished=True)] == [12340, 12399]


async def test_hasmanagerpermsbyuserandids_uses_guild_settings_arrays():
    cog = make_cog()
    cog.bot.polls_api.get_guild = AsyncMock(return_value=GuildSettings(**make_guild_dict()))
    user = MagicMock()
    user.roles = [MagicMock(id=302)]
    assert await cog.hasmanagerpermsbyuserandids(user, 100, channel_id=301) == [100]
    cog.bot.polls_api.get_guild = AsyncMock(return_value=GuildSettings(**make_guild_dict(manager_role_id=[999])))
    assert await cog.hasmanagerpermsbyuserandids(user, 100, channel_id=999) == []


async def test_on_startup_buttons_uses_composed_fetch():
    cog = make_cog()
    cog.fetchallpolls = AsyncMock(
        return_value=[{"id": 1, "time": datetime(2026, 1, 1, tzinfo=timezone.utc), "active": True, "persistent": False, "published": True}]
    )
    cog.poll_buttons = AsyncMock()
    cog.bot.add_view = MagicMock()
    await cog.on_startup_buttons()
    cog.fetchallpolls.assert_awaited_once_with()
    cog.bot.add_view.assert_called_once()


async def test_on_startup_selfassign_filters_roles_client_side():
    cog = make_cog()
    cog.fetchalltags = AsyncMock(
        return_value=[
            make_tag_dict(end_message_self_assign=True, end_message_role_ids=[1, 2]),
            make_tag_dict(tag=2, end_message_self_assign=True, end_message_role_ids=[]),
            make_tag_dict(tag=3, end_message_self_assign=False, end_message_role_ids=[5]),
        ]
    )
    cog.bot.add_view = MagicMock()
    await cog.on_startup_selfassign()
    cog.fetchalltags.assert_awaited_once_with(end_message_self_assign="true")
    cog.bot.add_view.assert_called_once()


async def test_pollsme_votes_and_polls_come_from_api():
    cog = make_cog()
    cog.bot.polls_api.get_user_votes = AsyncMock(
        return_value=[UserVote(id=1, user_id=1234, poll_id=42, choice=1)]
    )
    cog.bot.polls_api.sync_all_polls = AsyncMock(
        return_value=[make_poll_model(id=42)]
    )
    cog.fetchguildid = AsyncMock(return_value=100)
    cog.canview = AsyncMock(return_value=False)
    cog.fetchcolourbyid = AsyncMock(return_value=1)
    cog.sortpolls = lambda polls, sort: polls

    interaction = MagicMock()
    interaction.guild_id = 100
    interaction.user = MagicMock()
    interaction.user.id = 1234
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    msg = MagicMock()
    msg.edit = AsyncMock()
    interaction.followup.send.return_value = msg

    await cog.pollsme(interaction)
    cog.bot.polls_api.sync_all_polls.assert_awaited_once()
    kwargs = cog.bot.polls_api.sync_all_polls.await_args.kwargs
    assert kwargs["guildId"] == 100
    assert kwargs["ids"] == "42"


def make_interaction():
    interaction = MagicMock()
    interaction.guild_id = 100
    interaction.user = MagicMock()
    interaction.user.id = 1234
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    msg = MagicMock()
    msg.edit = AsyncMock()
    interaction.followup.send.return_value = msg
    return interaction


async def test_pollsme_show_unvoted_composes_tag_and_guild_keys():
    cog = make_cog()
    cog.bot.polls_api.get_user_votes = AsyncMock(return_value=[])
    cog.bot.polls_api.sync_all_polls = AsyncMock(return_value=[make_poll_model()])
    cog.bot.polls_api.get_guild = AsyncMock(return_value=GuildSettings(**make_guild_dict()))
    cog.bot.polls_api.get_tags = AsyncMock(return_value=[Tag(**make_tag_dict())])
    cog.fetchguildid = AsyncMock(return_value=100)
    cog.fetchcolourbyid = AsyncMock(return_value=1)
    cog.sortpolls = lambda polls, sort: polls
    seen = []
    cog.canview = AsyncMock(side_effect=lambda poll, guild_id: seen.append(poll) or False)

    await cog.pollsme(make_interaction(), show_unvoted=True)

    cog.bot.polls_api.sync_all_polls.assert_awaited_once_with(guildId=100, live="true")
    assert seen[0]["channel_id"] == 200
    assert seen[0]["fallback_channel_id"] == 303


async def test_pollsme_no_votes_makes_no_wasted_fetches():
    cog = make_cog()
    cog.bot.polls_api.get_user_votes = AsyncMock(return_value=[])
    cog.bot.polls_api.sync_all_polls = AsyncMock(return_value=[])
    cog.fetchguildid = AsyncMock(return_value=100)
    cog.fetchcolourbyid = AsyncMock(return_value=1)

    await cog.pollsme(make_interaction())

    cog.bot.polls_api.sync_all_polls.assert_not_awaited()
    assert cog.fetchguildid.await_count == 1


async def test_admin_sync_skips_update_votes_task():
    cog = make_cog()
    cog.fetchallpolls = AsyncMock(return_value=[])
    cog.schedule_starts = AsyncMock()
    cog.schedule_ends = AsyncMock()
    cog.on_startup_selfassign = AsyncMock()
    cog.do_updatepollmessage = AsyncMock()

    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    msg = MagicMock()
    msg.edit = AsyncMock()
    interaction.followup.send = AsyncMock(return_value=msg)

    await cog.polladminsync(interaction)
    cog.fetchallpolls.assert_awaited_once_with()
    cog.schedule_starts.assert_awaited_once()
    cog.schedule_ends.assert_awaited_once()
    cog.on_startup_selfassign.assert_awaited_once()
