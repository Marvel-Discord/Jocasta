"""Tests for the one-shot newschannelsping migration script."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts.migrate_newschannelsping import migrate


@pytest.mark.asyncio
async def test_migrate_copies_rows_to_redis(fake_redis):
    """Each Postgres row becomes a Redis key."""
    conn = AsyncMock()
    conn.fetch.return_value = [
        {"channel_id": 123, "latest_message_id": 456},
        {"channel_id": 789, "latest_message_id": 101112},
    ]

    count = await migrate(conn, fake_redis)

    assert count == 2
    assert await fake_redis.get("jocasta:bot:newschannelsping:123") == "456"
    assert await fake_redis.get("jocasta:bot:newschannelsping:789") == "101112"


@pytest.mark.asyncio
async def test_migrate_skips_null_latest_message_id(fake_redis):
    """Rows with NULL latest_message_id should not be migrated."""
    conn = AsyncMock()
    conn.fetch.return_value = []  # SQL filters these out already

    count = await migrate(conn, fake_redis)

    assert count == 0


@pytest.mark.asyncio
async def test_migrate_is_idempotent(fake_redis):
    """Running twice produces the same state."""
    conn = AsyncMock()
    conn.fetch.return_value = [
        {"channel_id": 123, "latest_message_id": 456},
    ]

    await migrate(conn, fake_redis)
    await migrate(conn, fake_redis)

    assert await fake_redis.get("jocasta:bot:newschannelsping:123") == "456"


@pytest.mark.asyncio
async def test_migrate_uses_correct_sql_filter():
    """The SQL should filter out NULL latest_message_id rows."""
    conn = AsyncMock()
    conn.fetch.return_value = []

    await migrate(conn, MagicMock())

    conn.fetch.assert_awaited_once()
    sql_arg = conn.fetch.call_args.args[0]
    assert "WHERE latest_message_id IS NOT NULL" in sql_arg
