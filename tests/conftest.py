"""Shared pytest fixtures for the Jocasta bot test suite."""
from unittest.mock import MagicMock

import pytest
import fakeredis.aioredis


@pytest.fixture
def fake_redis():
    """A fresh in-memory Redis instance for each test."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def mock_bot(fake_redis):
    """A minimal bot stand-in with bot.redis attached.

    Later tasks will expand this fixture as more cog behavior is tested.
    FakeBot provides the attributes cogs touch in __init__ (tree, loop)
    so that e.g. NewsCog(mock_bot) constructs cleanly in tests.
    """
    class FakeBot:
        def __init__(self):
            self.redis = fake_redis
            self.db = None  # still present for cogs that use it
            self.tree = MagicMock()
            self.loop = MagicMock()
            # NewsCog schedules on_startup_scheduler() via loop.create_task;
            # close the coroutine so tests don't emit "never awaited" warnings
            self.loop.create_task.side_effect = lambda coro: coro.close()
    return FakeBot()
