"""Tests for cogs/news.py send_news_ping Redis interaction.

These tests stub out everything Discord-related and focus on the Redis
read/write behavior and graceful degradation.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.news import NewsCog


def _make_message(channel_id=111, author_id=222, embeds=None, content=""):
    """Build a minimal discord.Message mock."""
    msg = MagicMock(spec=discord.Message)
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.channel.id = channel_id
    msg.channel.send = AsyncMock()
    msg.channel.fetch_message = AsyncMock()
    msg.author = MagicMock()
    msg.author.id = author_id
    msg.created_at = discord.utils.utcnow()
    msg.embeds = embeds or []
    msg.content = content
    msg.flags = MagicMock()
    msg.flags.suppress_notifications = False
    return msg


@pytest.mark.asyncio
async def test_send_news_ping_writes_message_id_to_redis(mock_bot, fake_redis):
    """After sending a news ping, the message_id should be stored in Redis."""
    cog = NewsCog(mock_bot)
    cog.newsrole = MagicMock()
    cog.newsrole.mention = "@news"
    cog.newslock = asyncio.Lock()

    msg = _make_message(channel_id=999)
    new_discord_msg = MagicMock()
    new_discord_msg.id = 555555
    msg.channel.send.return_value = new_discord_msg

    await cog.send_news_ping(msg)

    assert await fake_redis.get("jocasta:bot:newschannelsping:999") == "555555"


@pytest.mark.asyncio
async def test_send_news_ping_reads_existing_message_id(mock_bot, fake_redis):
    """If Redis has a previous message_id, the cog should try to edit that message."""
    await fake_redis.set("jocasta:bot:newschannelsping:999", "888888")

    cog = NewsCog(mock_bot)
    cog.newsrole = MagicMock()
    cog.newsrole.mention = "@news"
    cog.newslock = asyncio.Lock()

    old_msg = MagicMock()
    old_msg.created_at = discord.utils.utcnow()
    old_msg.content = "@news *existing title*"
    old_msg.edit = AsyncMock()

    msg = _make_message(channel_id=999)
    msg.channel.fetch_message.return_value = old_msg

    await cog.send_news_ping(msg)

    # Should have edited the old message instead of sending a new one
    old_msg.edit.assert_awaited_once()
    msg.channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_news_ping_degrades_when_redis_is_none(mock_bot):
    """If bot.redis is None (Redis unavailable), the ping still sends."""
    mock_bot.redis = None

    cog = NewsCog(mock_bot)
    cog.newsrole = MagicMock()
    cog.newsrole.mention = "@news"
    cog.newslock = asyncio.Lock()

    msg = _make_message(channel_id=999)
    new_discord_msg = MagicMock()
    new_discord_msg.id = 555555
    msg.channel.send.return_value = new_discord_msg

    # Should not raise
    await cog.send_news_ping(msg)

    msg.channel.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_news_ping_handles_redis_read_failure(mock_bot, fake_redis):
    """If Redis read throws, the cog should still send a new message."""
    failing_redis = AsyncMock()
    failing_redis.get.side_effect = ConnectionError("Redis gone")
    failing_redis.set = AsyncMock()
    mock_bot.redis = failing_redis

    cog = NewsCog(mock_bot)
    cog.newsrole = MagicMock()
    cog.newsrole.mention = "@news"
    cog.newslock = asyncio.Lock()

    msg = _make_message(channel_id=999)
    new_discord_msg = MagicMock()
    new_discord_msg.id = 555555
    msg.channel.send.return_value = new_discord_msg

    await cog.send_news_ping(msg)

    msg.channel.send.assert_awaited_once()
