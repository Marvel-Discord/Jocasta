"""Tests for the five-minute TTL cache in front of fetch_all_tags."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import discord
from funcs.polls_api import PollsAPIError
from funcs.polls_api_models import Tag
from tests.conftest import unwrap_command

from cogs.polls import PollsCog


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


def make_cog():
    class FakeBot:
        guilds: list
        add_view: MagicMock

        def __init__(self):
            self.tasks = {}
            self.tree = MagicMock()
            self.loop = MagicMock()
            self.loop.create_task.side_effect = lambda coro: coro.close()
            self.polls_api = MagicMock()

    cog = PollsCog(FakeBot())
    cog._home_guild_ids = [288896937074360321]
    unwrap_command(cog, "poll_admin_sync")
    return cog


class FakeClock:
    """Monkeypatches discord.utils.utcnow so tests control time."""

    def __init__(self, start: datetime):
        self.now = start

    def utcnow(self):
        return self.now

    def advance(self, **kwargs):
        self.now = self.now + timedelta(**kwargs)


def install_clock(monkeypatch, start=None):
    clock = FakeClock(start or datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
    monkeypatch.setattr(discord.utils, "utcnow", clock.utcnow)
    return clock


async def test_first_fetch_hits_api_and_second_within_ttl_is_cached(monkeypatch):
    clock = install_clock(monkeypatch)
    cog = make_cog()
    cog.bot.polls_api.get_tags = AsyncMock(return_value=[Tag(**make_tag_dict())])

    first = await cog.fetch_all_tags()
    assert [t["name"] for t in first] == ["comics"]
    cog.bot.polls_api.get_tags.assert_awaited_once_with()

    clock.advance(seconds=299)
    second = await cog.fetch_all_tags()
    assert second is first
    cog.bot.polls_api.get_tags.assert_awaited_once_with()


async def test_refetches_after_ttl_expiry(monkeypatch):
    clock = install_clock(monkeypatch)
    cog = make_cog()
    cog.bot.polls_api.get_tags = AsyncMock(return_value=[Tag(**make_tag_dict())])

    await cog.fetch_all_tags()
    clock.advance(seconds=300)
    await cog.fetch_all_tags()
    assert cog.bot.polls_api.get_tags.await_count == 2


async def test_cache_is_per_params(monkeypatch):
    install_clock(monkeypatch)
    cog = make_cog()
    cog.bot.polls_api.get_tags = AsyncMock(return_value=[Tag(**make_tag_dict())])

    plain = await cog.fetch_all_tags()
    self_assign = await cog.fetch_all_tags(end_message_self_assign=True)
    replace = await cog.fetch_all_tags(end_message_replace=True)
    assert cog.bot.polls_api.get_tags.await_count == 3
    cog.bot.polls_api.get_tags.assert_any_await()
    cog.bot.polls_api.get_tags.assert_any_await(end_message_self_assign=True)
    cog.bot.polls_api.get_tags.assert_any_await(end_message_replace=True)

    # revisits within the TTL are served from each combo's own entry
    assert await cog.fetch_all_tags() is plain
    assert await cog.fetch_all_tags(end_message_self_assign=True) is self_assign
    assert await cog.fetch_all_tags(end_message_replace=True) is replace
    assert cog.bot.polls_api.get_tags.await_count == 3


async def test_empty_tag_list_is_cached(monkeypatch):
    """get_tags returns a list (it has no 404 miss state), so an empty
    tag list is valid state and is cached like any other result."""
    clock = install_clock(monkeypatch)
    cog = make_cog()
    cog.bot.polls_api.get_tags = AsyncMock(return_value=[])

    assert await cog.fetch_all_tags() == []
    clock.advance(seconds=299)
    assert await cog.fetch_all_tags() == []
    cog.bot.polls_api.get_tags.assert_awaited_once_with()


async def test_api_errors_raise_through_uncached(monkeypatch):
    install_clock(monkeypatch)
    cog = make_cog()
    cog.bot.polls_api.get_tags = AsyncMock(side_effect=PollsAPIError(500, "boom"))
    try:
        await cog.fetch_all_tags()
    except PollsAPIError:
        pass
    else:
        raise AssertionError("expected PollsAPIError to raise through")

    cog.bot.polls_api.get_tags = AsyncMock(return_value=[Tag(**make_tag_dict())])
    assert [t["name"] for t in await cog.fetch_all_tags()] == ["comics"]


async def test_admin_sync_clears_cache(monkeypatch):
    install_clock(monkeypatch)
    cog = make_cog()
    cog.bot.polls_api.get_tags = AsyncMock(return_value=[Tag(**make_tag_dict())])
    await cog.fetch_all_tags()
    cog.bot.polls_api.get_tags.assert_awaited_once_with()

    cog.fetch_all_polls = AsyncMock(return_value=[])
    cog.process_pending_renders = AsyncMock()
    cog.process_missed_ends = AsyncMock()
    cog.on_startup_self_assign = AsyncMock()
    cog.do_update_poll_message = AsyncMock()

    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    msg = MagicMock()
    msg.edit = AsyncMock()
    interaction.followup.send = AsyncMock(return_value=msg)

    await cog.poll_admin_sync(interaction)

    await cog.fetch_all_tags()
    assert cog.bot.polls_api.get_tags.await_count == 2


async def test_id_autocomplete_flow_hits_tags_api_once_within_ttl(monkeypatch):
    """Two successive keystrokes through the id-autocomplete helper (which
    calls fetch_all_tags for local filtering each time) hit get_tags exactly
    once thanks to the cache."""
    install_clock(monkeypatch)
    cog = make_cog()
    cog.bot.polls_api.get_tags = AsyncMock(return_value=[Tag(**make_tag_dict())])
    cog.search_polls_by_id = AsyncMock(return_value=[])
    cog.has_manager_perms = AsyncMock(return_value=[])

    interaction = MagicMock()
    interaction.guild_id = 100

    await cog.autocomplete_search_by_poll_id(interaction, "1")
    await cog.autocomplete_search_by_poll_id(interaction, "12")
    cog.bot.polls_api.get_tags.assert_awaited_once_with()
