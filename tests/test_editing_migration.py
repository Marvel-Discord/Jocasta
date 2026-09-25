"""Tests for the editing migration from postgres to the polls API."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from cogs.polls import PollsCog
from funcs.polls_api import PollsAPIError
from funcs.polls_api_models import GuildSettings, Poll, Tag, UserVote


def make_cog():
    class FakeBot:
        def __init__(self):
            self.tasks = {"poll_schedules": {"starts": {}, "ends": {}}}
            self.tree = MagicMock()
            self.loop = MagicMock()
            self.loop.create_task.side_effect = lambda coro: coro.close()
            self.polls_api = MagicMock()
            self.wait_until_ready = AsyncMock()

    cog = PollsCog(FakeBot())
    cog.guild_ids = [288896937074360321]
    cog.pollsme = PollsCog.pollsme._callback.__get__(cog)
    cog.polladminsync = PollsCog.polladminsync._callback.__get__(cog)
    cog.poll_schedule = PollsCog.poll_schedule._callback.__get__(cog)
    cog.poll_start = PollsCog.poll_start._callback.__get__(cog)
    cog.poll_end = PollsCog.poll_end._callback.__get__(cog)
    cog.poll_delete = PollsCog.poll_delete._callback.__get__(cog)
    cog.poll_edit = PollsCog.poll_edit._callback.__get__(cog)
    cog.poll_create = PollsCog.poll_create._callback.__get__(cog)
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
        "channel_id": 300,
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


def make_channel(channel_id=300, msg_id=5555):
    channel = MagicMock()
    channel.id = channel_id
    msg = MagicMock()
    msg.id = msg_id
    channel.send = AsyncMock(return_value=msg)
    return channel


async def test_poll_delete_confirmed_calls_delete_polls_with_user():
    cog = make_cog()
    poll_dict = cog.poll_dict(make_poll_model(published=False))
    cog.fetch_poll = AsyncMock(return_value=poll_dict)
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.pollinfoembed = AsyncMock(return_value=MagicMock())
    cog.bot.polls_api.delete_polls = AsyncMock(return_value={"deletedCount": 1})

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.channel_id = 301
    interaction.response.defer = AsyncMock()
    msg = MagicMock()
    msg.edit = AsyncMock()
    interaction.followup.send = AsyncMock(return_value=msg)

    async def instant_confirm_wait(self):
        self.value = True

    original_wait = PollsCog.Confirm.wait
    PollsCog.Confirm.wait = instant_confirm_wait
    try:
        await cog.poll_delete(interaction, 42)
    finally:
        PollsCog.Confirm.wait = original_wait

    cog.bot.polls_api.delete_polls.assert_awaited_once_with([42], 1234)
    msg.edit.assert_awaited()


async def test_poll_delete_api_error_sends_ephemeral_reply():
    cog = make_cog()
    poll_dict = cog.poll_dict(make_poll_model(published=False))
    cog.fetch_poll = AsyncMock(return_value=poll_dict)
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.pollinfoembed = AsyncMock(return_value=MagicMock())
    cog.bot.polls_api.delete_polls = AsyncMock(side_effect=PollsAPIError(503, "down"))

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.channel_id = 301
    interaction.response.defer = AsyncMock()
    msg = MagicMock()
    msg.edit = AsyncMock()
    interaction.followup.send = AsyncMock(return_value=msg)

    async def instant_confirm_wait(self):
        self.value = True

    original_wait = PollsCog.Confirm.wait
    PollsCog.Confirm.wait = instant_confirm_wait
    try:
        await cog.poll_delete(interaction, 42)
    finally:
        PollsCog.Confirm.wait = original_wait

    cog.bot.polls_api.delete_polls.assert_awaited_once_with([42], 1234)
    assert any(
        call.kwargs.get("ephemeral") is True
        for call in interaction.followup.send.await_args_list
    )


async def test_poll_edit_param_path_sends_full_body_with_user():
    cog = make_cog()
    poll_dict = cog.poll_dict(make_poll_model(published=False))
    cog.fetch_poll = AsyncMock(return_value=poll_dict)
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.bot.polls_api.update_polls = AsyncMock(return_value=[poll_dict])
    cog.fetch_guild_info = AsyncMock(return_value=make_guild_dict())
    cog.fetch_tag = AsyncMock(return_value=make_tag_dict())
    cog.pollinfoembed = AsyncMock(return_value=MagicMock())

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.channel_id = 301
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_edit(interaction, 42, question="New question?", opt_1="A1", description="-clear")

    cog.bot.polls_api.update_polls.assert_awaited_once()
    body = cog.bot.polls_api.update_polls.await_args.args[0][0]
    assert cog.bot.polls_api.update_polls.await_args.args[1] == 1234
    assert body["id"] == 42
    assert body["question"] == "New question?"
    assert body["choices"] == ["A1", "B"]
    assert body["description"] is None
    assert "tag" not in body and "show_voting" not in body and "image" not in body


async def test_poll_edit_clear_image_sends_null():
    cog = make_cog()
    poll_dict = cog.poll_dict(make_poll_model(published=False, image="http://x"))
    cog.fetch_poll = AsyncMock(return_value=poll_dict)
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.bot.polls_api.update_polls = AsyncMock(return_value=[poll_dict])
    cog.fetch_guild_info = AsyncMock(return_value=make_guild_dict())
    cog.fetch_tag = AsyncMock(return_value=make_tag_dict())
    cog.pollinfoembed = AsyncMock(return_value=MagicMock())

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.channel_id = 301
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_edit(interaction, 42, image="-clear")

    body = cog.bot.polls_api.update_polls.await_args.args[0][0]
    assert body["image"] is None
    assert body["question"] == "Best hero?"


async def test_poll_edit_api_error_sends_ephemeral_reply():
    cog = make_cog()
    poll_dict = cog.poll_dict(make_poll_model(published=False))
    cog.fetch_poll = AsyncMock(return_value=poll_dict)
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.bot.polls_api.update_polls = AsyncMock(side_effect=PollsAPIError(403, "denied"))
    cog.fetch_guild_info = AsyncMock(return_value=make_guild_dict())
    cog.fetch_tag = AsyncMock(return_value=make_tag_dict())
    cog.pollinfoembed = AsyncMock(return_value=MagicMock())

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.channel_id = 301
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_edit(interaction, 42, question="X?")

    assert any(
        call.kwargs.get("ephemeral") is True
        for call in interaction.followup.send.await_args_list
    )


async def test_poll_create_sends_body_without_id_and_uses_assigned_id():
    cog = make_cog()
    created = make_poll_model(id=777, published=False)
    cog.fetchguildid = AsyncMock(return_value=100)
    cog.validtag = AsyncMock(return_value=make_tag_dict())
    cog.bot.polls_api.create_polls = AsyncMock(return_value=[created])
    cog.fetch_poll = AsyncMock(return_value=cog.poll_dict(created))
    cog.pollinfoembed = AsyncMock(return_value=MagicMock())

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.guild_id = 100
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_create(interaction, question="Q?", opt_1="A", opt_2="B", tag="1")

    cog.bot.polls_api.create_polls.assert_awaited_once()
    polls_arg, user_arg = cog.bot.polls_api.create_polls.await_args.args
    assert user_arg == 1234
    assert "id" not in polls_arg[0]
    assert polls_arg[0]["question"] == "Q?"
    assert polls_arg[0]["choices"] == ["A", "B"]
    assert polls_arg[0]["tag"] == 1
    assert polls_arg[0]["guild_id"] == 100
    cog.fetch_poll.assert_awaited_with(777)


async def test_poll_create_without_tag_is_rejected():
    cog = make_cog()
    cog.fetchguildid = AsyncMock(return_value=100)
    cog.bot.polls_api.create_polls = AsyncMock()

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.guild_id = 100
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_create(interaction, question="Q?", opt_1="A", opt_2="B")

    cog.bot.polls_api.create_polls.assert_not_awaited()
    assert "tag" in interaction.followup.send.await_args.args[0]


async def test_poll_create_api_error_sends_ephemeral_reply():
    cog = make_cog()
    cog.fetchguildid = AsyncMock(return_value=100)
    cog.validtag = AsyncMock(return_value=make_tag_dict())
    cog.bot.polls_api.create_polls = AsyncMock(side_effect=PollsAPIError(0, "network error"))

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.guild_id = 100
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_create(interaction, question="Q?", opt_1="A", opt_2="B", tag="1")

    assert any(
        call.kwargs.get("ephemeral") is True
        for call in interaction.followup.send.await_args_list
    )
