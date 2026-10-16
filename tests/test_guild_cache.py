"""Tests for the five-minute TTL cache in front of fetch_guild_info."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import discord
from funcs.polls_api import PollsAPIError
from funcs.polls_api_models import GuildSettings
from tests.conftest import unwrap_command

from cogs.polls import PollsCog


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
    cog.bot.polls_api.get_guild = AsyncMock(
        return_value=GuildSettings(**make_guild_dict())
    )

    first = await cog.fetch_guild_info(100)
    assert first["default_channel_id"] == 300
    cog.bot.polls_api.get_guild.assert_awaited_once_with(100)

    clock.advance(seconds=299)
    second = await cog.fetch_guild_info(100)
    assert second["default_channel_id"] == 300
    cog.bot.polls_api.get_guild.assert_awaited_once_with(100)


async def test_refetches_after_ttl_expiry(monkeypatch):
    clock = install_clock(monkeypatch)
    cog = make_cog()
    cog.bot.polls_api.get_guild = AsyncMock(
        return_value=GuildSettings(**make_guild_dict())
    )

    await cog.fetch_guild_info(100)
    clock.advance(seconds=300)
    await cog.fetch_guild_info(100)
    assert cog.bot.polls_api.get_guild.await_count == 2


async def test_cache_is_per_guild(monkeypatch):
    install_clock(monkeypatch)
    cog = make_cog()
    cog.bot.polls_api.get_guild = AsyncMock(
        return_value=GuildSettings(**make_guild_dict())
    )

    await cog.fetch_guild_info(100)
    await cog.fetch_guild_info(200)
    assert cog.bot.polls_api.get_guild.await_count == 2


async def test_404_miss_is_not_cached(monkeypatch):
    install_clock(monkeypatch)
    cog = make_cog()
    cog.bot.polls_api.get_guild = AsyncMock(side_effect=PollsAPIError(404, "not found"))
    assert await cog.fetch_guild_info(100) is None

    cog.bot.polls_api.get_guild = AsyncMock(
        return_value=GuildSettings(**make_guild_dict())
    )
    guild = await cog.fetch_guild_info(100)
    assert guild is not None
    assert cog.bot.polls_api.get_guild.await_count == 1


async def test_other_errors_raise_through_uncached(monkeypatch):
    install_clock(monkeypatch)
    cog = make_cog()
    cog.bot.polls_api.get_guild = AsyncMock(side_effect=PollsAPIError(500, "boom"))
    try:
        await cog.fetch_guild_info(100)
    except PollsAPIError:
        pass
    else:
        raise AssertionError("expected PollsAPIError to raise through")

    cog.bot.polls_api.get_guild = AsyncMock(
        return_value=GuildSettings(**make_guild_dict())
    )
    assert await cog.fetch_guild_info(100) is not None


async def test_admin_sync_clears_cache(monkeypatch):
    install_clock(monkeypatch)
    cog = make_cog()
    cog.bot.polls_api.get_guild = AsyncMock(
        return_value=GuildSettings(**make_guild_dict())
    )
    await cog.fetch_guild_info(100)
    cog.bot.polls_api.get_guild.assert_awaited_once_with(100)

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

    await cog.fetch_guild_info(100)
    assert cog.bot.polls_api.get_guild.await_count == 2


async def test_fetch_guild_info_by_manage_channel_benefits_from_cache(monkeypatch):
    install_clock(monkeypatch)
    cog = make_cog()
    cog.bot.polls_api.get_guild = AsyncMock(
        return_value=GuildSettings(**make_guild_dict())
    )

    assert await cog.fetch_guild_info_by_manage_channel(301) is not None
    assert await cog.fetch_guild_info_by_manage_channel(999) is None
    cog.bot.polls_api.get_guild.assert_awaited_once_with(288896937074360321)
