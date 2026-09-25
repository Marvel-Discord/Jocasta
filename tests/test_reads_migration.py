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


async def test_poll_dict_synthesizes_duration_and_merges_tag_guild():
    cog = make_cog()
    d = cog.poll_dict(make_poll_model(), make_tag_dict(), make_guild_dict())
    assert d["duration"] == timedelta(days=4)
    assert d["channel_id"] == 200
    assert d["persistent"] is False
    assert d["default_channel_id"] == 300
    assert d["fallback_channel_id"] == 303
    assert d["time"] == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    assert d["votes"] == [3, 1]
    assert d["active"] is True


async def test_poll_dict_missing_times_gives_none_duration():
    cog = make_cog()
    d = cog.poll_dict(make_poll_model(start_time=None, end_time=None, time=None))
    assert d["duration"] is None


async def test_fetch_all_polls_composes_join_shape_and_filters_published():
    cog = make_cog()
    cog.bot.polls_api.sync_all_polls = AsyncMock(
        return_value=[make_poll_model(id=1), make_poll_model(id=2, published=False)]
    )
    cog.bot.polls_api.get_guild = AsyncMock(return_value=GuildSettings(**make_guild_dict()))
    cog.bot.polls_api.get_tags = AsyncMock(return_value=[Tag(**make_tag_dict())])

    published_only = await cog.fetch_all_polls()
    assert [p["id"] for p in published_only] == [1]
    assert published_only[0]["name"] == "comics"

    everything = await cog.fetch_all_polls(show_unpublished=True)
    assert [p["id"] for p in everything] == [1, 2]
    cog.bot.polls_api.sync_all_polls.assert_awaited_with(guildId=288896937074360321)


def test_polls_guild_id_prefers_guild_ids_attr():
    cog = make_cog()
    assert cog.polls_guild_id() == 288896937074360321
    cog.guild_ids = None
    cog.bot.guilds = [MagicMock(id=999)]
    assert cog.polls_guild_id() == 999


def test_search_matches_passes_when_no_filters_set():
    cog = make_cog()
    poll = make_poll_model(published=True, active=True)

    assert cog.search_matches(poll, 1, None, None, "-1") is True
    assert cog.search_matches(poll, 1, True, True, "-1") is True


def test_search_matches_filters_published_and_active():
    cog = make_cog()
    poll = make_poll_model(published=True, active=True)

    assert cog.search_matches(poll, 1, False, None, "-1") is False
    assert cog.search_matches(poll, 1, None, False, "-1") is False
    assert cog.search_matches(poll, 1, False, False, "-1") is False


def test_search_matches_notag_matches_nothing_for_tagged_polls():
    cog = make_cog()
    poll = make_poll_model(tag=1)

    assert cog.search_matches(poll, -1, None, None, "-1") is False


from funcs.polls_api import PollsAPIError


async def test_fetch_poll_returns_none_on_404():
    cog = make_cog()
    cog.bot.polls_api.get_poll = AsyncMock(side_effect=PollsAPIError(404, "not found"))
    cog.fetch_tag = AsyncMock(return_value=None)
    cog.fetch_guild_info = AsyncMock(return_value=None)
    assert await cog.fetch_poll(42) is None


async def test_fetch_poll_composes_poll_tag_guild():
    cog = make_cog()
    cog.bot.polls_api.get_poll = AsyncMock(return_value=make_poll_model())
    cog.fetch_tag = AsyncMock(return_value=make_tag_dict())
    cog.fetch_guild_info = AsyncMock(return_value=make_guild_dict())
    poll = await cog.fetch_poll(42)
    assert poll["id"] == 42
    assert poll["name"] == "comics"
    assert poll["default_channel_id"] == 300
    cog.bot.polls_api.get_poll.assert_awaited_once_with(42)


async def test_fetch_guild_info_returns_dict_or_none_on_404():
    cog = make_cog()
    cog.bot.polls_api.get_guild = AsyncMock(return_value=GuildSettings(**make_guild_dict()))
    assert (await cog.fetch_guild_info(100))["default_channel_id"] == 300
    cog.bot.polls_api.get_guild = AsyncMock(side_effect=PollsAPIError(404, "nope"))
    assert await cog.fetch_guild_info(100) is None


async def test_fetch_guild_info_by_manage_channel_checks_home_guild_array():
    cog = make_cog()
    cog.bot.polls_api.get_guild = AsyncMock(return_value=GuildSettings(**make_guild_dict()))
    assert (await cog.fetch_guild_info_by_manage_channel(301))["guild_id"] == 100
    assert await cog.fetch_guild_info_by_manage_channel(999) is None


async def test_fetch_tag_returns_dict_none_on_falsy_and_404():
    cog = make_cog()
    cog.bot.polls_api.get_tag = AsyncMock(return_value=Tag(**make_tag_dict()))
    assert (await cog.fetch_tag(1))["name"] == "comics"
    cog.bot.polls_api.get_tag = AsyncMock(side_effect=PollsAPIError(404, "nope"))
    assert await cog.fetch_tag(1) is None
    cog.bot.polls_api.get_tag = AsyncMock(return_value=Tag(**make_tag_dict()))
    assert await cog.fetch_tag(0) is None
    cog.bot.polls_api.get_tag.assert_not_awaited()


async def test_fetch_all_tags_and_fetch_tags_by_guild_id_filter_client_side():
    cog = make_cog()
    cog.bot.polls_api.get_tags = AsyncMock(
        return_value=[Tag(**make_tag_dict()), Tag(**make_tag_dict(tag=2, guild_id=100))]
    )
    assert len(await cog.fetch_all_tags()) == 2
    cog.bot.polls_api.get_tags = AsyncMock(
        return_value=[Tag(**make_tag_dict()), Tag(**make_tag_dict(tag=2, guild_id=777))]
    )
    assert [t["tag"] for t in await cog.fetch_tags_by_guild_id(100)] == [1]


async def test_search_polls_by_id_prefix_filters_over_full_fetch():
    cog = make_cog()
    cog.fetch_all_polls = AsyncMock(
        return_value=[{"id": 12340, "published": True}, {"id": 12399, "published": False}, {"id": 55555, "published": True}]
    )
    assert [p["id"] for p in await cog.search_polls_by_id(123)] == [12340]
    assert [p["id"] for p in await cog.search_polls_by_id(123, show_unpublished=True)] == [12340, 12399]


async def test_has_manager_perms_by_user_and_ids_uses_guild_settings_arrays():
    cog = make_cog()
    cog.bot.polls_api.get_guild = AsyncMock(return_value=GuildSettings(**make_guild_dict()))
    user = MagicMock()
    user.roles = [MagicMock(id=302)]
    assert await cog.has_manager_perms_by_user_and_ids(user, 100, channel_id=301) == [100]
    cog.bot.polls_api.get_guild = AsyncMock(return_value=GuildSettings(**make_guild_dict(manager_role_id=[999])))
    assert await cog.has_manager_perms_by_user_and_ids(user, 100, channel_id=999) == []


async def test_on_startup_buttons_uses_composed_fetch():
    cog = make_cog()
    cog.fetch_all_polls = AsyncMock(
        return_value=[{"id": 1, "time": datetime(2026, 1, 1, tzinfo=timezone.utc), "active": True, "persistent": False, "published": True}]
    )
    cog.poll_buttons = AsyncMock()
    cog.bot.add_view = MagicMock()
    await cog.on_startup_buttons()
    cog.fetch_all_polls.assert_awaited_once_with()
    cog.bot.add_view.assert_called_once()


async def test_on_startup_self_assign_filters_roles_client_side():
    cog = make_cog()
    cog.fetch_all_tags = AsyncMock(
        return_value=[
            make_tag_dict(end_message_self_assign=True, end_message_role_ids=[1, 2]),
            make_tag_dict(tag=2, end_message_self_assign=True, end_message_role_ids=[]),
            make_tag_dict(tag=3, end_message_self_assign=False, end_message_role_ids=[5]),
        ]
    )
    cog.bot.add_view = MagicMock()
    await cog.on_startup_self_assign()
    cog.fetch_all_tags.assert_awaited_once_with(end_message_self_assign="true")
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
    cog.fetch_all_polls = AsyncMock(return_value=[])
    cog.schedule_starts = AsyncMock()
    cog.schedule_ends = AsyncMock()
    cog.on_startup_self_assign = AsyncMock()
    cog.do_updatepollmessage = AsyncMock()

    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    msg = MagicMock()
    msg.edit = AsyncMock()
    interaction.followup.send = AsyncMock(return_value=msg)

    await cog.polladminsync(interaction)
    cog.fetch_all_polls.assert_awaited_once_with(show_unpublished=False)
    cog.schedule_starts.assert_awaited_once()
    cog.schedule_ends.assert_awaited_once()
    cog.on_startup_self_assign.assert_awaited_once()
