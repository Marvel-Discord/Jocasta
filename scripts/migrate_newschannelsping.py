"""One-shot migration: copies newschannelsping rows from Postgres to Redis.

Usage:
    python -m scripts.migrate_newschannelsping

Run this BEFORE deploying the bot version that uses Redis. The old
newschannelsping Postgres table is NOT modified or dropped — it remains
as a rollback safety net.
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
