"""Copies the bot's news-ping tracking data from Postgres to Redis.

The news cog (cogs/news.py) remembers the latest news-ping message per
channel so it can edit or delete the previous ping instead of sending
duplicates. That used to live in the bot's only exclusive Postgres table,
`newschannelsping`; the bot now keeps it in its own Redis instance under
keys like `jocasta:bot:newschannelsping:<channel_id>`. This script copies
the existing rows across so the switch is seamless — run it once, before
the new bot version starts, ideally right before the restart. If it's
skipped (or an old-bot ping lands after it runs), the worst case is one
duplicate ping per channel, which self-corrects on the next ping.

Usage:
    python -m scripts.migrate_newschannelsping

Run from the repo root (the directory with main.py). Connection details
come from the environment (a .env in the repo root is loaded): the usual
POSTGRES_* variables plus REDIS_URL, which must point at the same
bot-owned Redis the bot is configured with. On success it prints the
number of rows migrated; each Redis key holds the message id as a string.

The script only reads Postgres — the table is deliberately left in place
as a rollback path (the previous bot version still reads it). Re-running
is safe before the new bot goes live, but don't re-run afterwards: the
running bot writes newer message ids to Redis only, and this would
overwrite them with the stale values from Postgres.
"""
import asyncio
import os

import asyncpg
import redis.asyncio as redis
from dotenv import load_dotenv

load_dotenv()

KEY_PREFIX = "jocasta:bot:newschannelsping:"


async def migrate(conn, r):
    """Copy newschannelsping rows from Postgres to Redis.

    Args:
        conn: an open asyncpg.Connection
        r: an open redis.asyncio.Redis client (with decode_responses=True)

    Returns:
        The number of rows migrated.
    """
    rows = await conn.fetch(
        "SELECT channel_id, latest_message_id FROM newschannelsping "
        "WHERE latest_message_id IS NOT NULL"
    )
    for row in rows:
        key = f"{KEY_PREFIX}{row['channel_id']}"
        await r.set(key, str(row["latest_message_id"]))
    return len(rows)


async def main():
    postgres_credentials = {
        "user": os.getenv("POSTGRES_USER"),
        "password": os.getenv("POSTGRES_PASSWORD"),
        "database": os.getenv("POSTGRES_DATABASE"),
        "host": os.getenv("POSTGRES_HOST"),
        "port": int(os.getenv("POSTGRES_PORT", 5432)),
    }
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    conn = await asyncpg.connect(**postgres_credentials)
    r = redis.from_url(redis_url, decode_responses=True)
    try:
        count = await migrate(conn, r)
        print(f"Migrated {count} rows from newschannelsping to Redis")
    finally:
        await conn.close()
        await r.aclose()


if __name__ == "__main__":
    asyncio.run(main())
