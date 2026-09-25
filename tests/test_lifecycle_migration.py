"""Tests for the lifecycle migration from postgres to the polls API."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from cogs.polls import PollsCog
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


async def test_poll_schedule_writes_start_time_via_update_polls():
    cog = make_cog()
    poll = make_poll_model(published=False, start_time=None, end_time=None, time=None)
    cog.fetch_poll = AsyncMock(return_value=cog.poll_dict(poll))
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.schedule_starts = AsyncMock()
    cog.fetchcolourbyid = AsyncMock(return_value=1)
    cog.bot.polls_api.update_polls = AsyncMock(return_value=[poll])

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.channel_id = 301
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_schedule(interaction, 42, schedule_time=1893456000)

    cog.bot.polls_api.update_polls.assert_awaited_once()
    body = cog.bot.polls_api.update_polls.await_args.args[0]
    assert body[0]["id"] == 42
    assert body[0]["question"] == "Best hero?"
    assert body[0]["choices"] == ["A", "B"]
    assert body[0]["start_time"] == "2030-01-01T00:00:00+00:00"
    assert cog.bot.polls_api.update_polls.await_args.args[1] == 1234
    cog.schedule_starts.assert_awaited_once()


async def test_poll_schedule_clear_schedule_sends_null_start_time():
    cog = make_cog()
    poll = make_poll_model(published=False)
    cog.fetch_poll = AsyncMock(return_value=cog.poll_dict(poll))
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.schedule_starts = AsyncMock()
    cog.fetchcolourbyid = AsyncMock(return_value=1)
    cog.bot.polls_api.update_polls = AsyncMock(return_value=[poll])

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_schedule(interaction, 42, schedule_time=-1)

    body = cog.bot.polls_api.update_polls.await_args.args[0]
    assert body[0]["start_time"] is None


async def test_poll_schedule_duration_computes_end_time():
    cog = make_cog()
    poll = make_poll_model(
        published=False,
        time=datetime(2030, 1, 1, tzinfo=timezone.utc),
        start_time=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    cog.fetch_poll = AsyncMock(return_value=cog.poll_dict(poll))
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.schedule_starts = AsyncMock()
    cog.schedule_ends = AsyncMock()
    cog.fetchcolourbyid = AsyncMock(return_value=1)
    cog.bot.polls_api.update_polls = AsyncMock(return_value=[poll])

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_schedule(interaction, 42, duration=3600)

    calls = cog.bot.polls_api.update_polls.await_args_list
    end_body = calls[-1].args[0][0]
    assert "end_time" in end_body
    assert end_body["end_time"] == "2030-01-01T01:00:00+00:00"
    assert end_body["id"] == 42


async def test_poll_schedule_duration_published_uses_now_plus_duration():
    cog = make_cog()
    poll = make_poll_model(published=True)
    cog.fetch_poll = AsyncMock(return_value=cog.poll_dict(poll))
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.schedule_starts = AsyncMock()
    cog.schedule_ends = AsyncMock()
    cog.fetchcolourbyid = AsyncMock(return_value=1)
    cog.bot.polls_api.update_polls = AsyncMock(return_value=[poll])

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_schedule(interaction, 42, duration=3600)

    calls = cog.bot.polls_api.update_polls.await_args_list
    end_body = calls[-1].args[0][0]
    assert "end_time" in end_body
    parsed = datetime.fromisoformat(end_body["end_time"])
    delta = parsed - datetime.now(timezone.utc)
    assert timedelta(hours=1) > delta > timedelta(minutes=59)
    assert end_body["id"] == 42


async def test_poll_schedule_duration_clear_sends_null_end_time():
    cog = make_cog()
    poll = make_poll_model(
        published=False,
        time=datetime(2030, 1, 1, tzinfo=timezone.utc),
        start_time=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    cog.fetch_poll = AsyncMock(return_value=cog.poll_dict(poll))
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.schedule_starts = AsyncMock()
    cog.schedule_ends = AsyncMock()
    cog.fetchcolourbyid = AsyncMock(return_value=1)
    cog.bot.polls_api.update_polls = AsyncMock(return_value=[poll])

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_schedule(interaction, 42, duration=-1)

    calls = cog.bot.polls_api.update_polls.await_args_list
    end_body = calls[-1].args[0][0]
    assert "end_time" in end_body
    assert end_body["end_time"] is None
    assert end_body["id"] == 42


def make_channel(channel_id=300, msg_id=5555):
    channel = MagicMock()
    channel.id = channel_id
    msg = MagicMock()
    msg.id = msg_id
    channel.send = AsyncMock(return_value=msg)
    return channel


async def test_start_polls_publishes_after_sending_with_collected_ids():
    cog = make_cog()
    tag = make_tag_dict(crosspost_channels=[201])
    poll_dict = cog.poll_dict(make_poll_model())
    cog.formatpollmessage = AsyncMock(return_value={"content": None, "embed": None, "view": None})
    cog.fetch_guild_info = AsyncMock(return_value=make_guild_dict())
    cog.fetch_poll = AsyncMock(return_value=poll_dict)
    cog.fetch_tag = AsyncMock(return_value=tag)
    cog.bot.polls_api.publish_poll = AsyncMock(return_value=poll_dict)
    cog.schedule_starts = AsyncMock()
    cog.schedule_ends = AsyncMock()
    cog.updatepollmessage = AsyncMock()

    main_channel = make_channel(300, msg_id=7001)
    crosspost_channel = make_channel(201, msg_id=7002)
    cog.bot.get_channel = MagicMock(
        side_effect=lambda cid: {300: main_channel, 201: crosspost_channel}.get(cid)
    )

    final = await cog.start_polls([42])

    cog.bot.polls_api.publish_poll.assert_awaited_once_with(42, 7001, [7002])
    main_channel.send.assert_awaited_once()
    crosspost_channel.send.assert_awaited_once()
    assert len(final) == 2


async def test_start_polls_no_crossposts_publishes_empty_array():
    cog = make_cog()
    tag = make_tag_dict(crosspost_channels=[])
    poll_dict = cog.poll_dict(make_poll_model())
    cog.formatpollmessage = AsyncMock(return_value={"content": None, "embed": None, "view": None})
    cog.fetch_guild_info = AsyncMock(return_value=make_guild_dict())
    cog.fetch_poll = AsyncMock(return_value=poll_dict)
    cog.fetch_tag = AsyncMock(return_value=tag)
    cog.bot.polls_api.publish_poll = AsyncMock(return_value=poll_dict)
    cog.schedule_starts = AsyncMock()
    cog.schedule_ends = AsyncMock()
    cog.updatepollmessage = AsyncMock()

    main_channel = make_channel(300, msg_id=7001)
    cog.bot.get_channel = MagicMock(side_effect=lambda cid: {300: main_channel}.get(cid))

    final = await cog.start_polls([42])

    cog.bot.polls_api.publish_poll.assert_awaited_once_with(42, 7001, [])
    assert len(final) == 1


async def test_poll_start_stamps_start_time_before_publish():
    cog = make_cog()
    poll_dict = cog.poll_dict(make_poll_model(published=False))
    cog.fetch_poll = AsyncMock(return_value=poll_dict)
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.bot.polls_api.update_polls = AsyncMock(return_value=[make_poll_model(published=False)])
    cog.start_poll = AsyncMock(return_value=[[poll_dict, MagicMock()]])

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_start(interaction, 42)

    cog.bot.polls_api.update_polls.assert_awaited_once()
    body = cog.bot.polls_api.update_polls.await_args.args[0][0]
    assert body["id"] == 42
    assert body["question"] == "Best hero?"
    assert body["choices"] == ["A", "B"]
    assert body["start_time"] is not None
    assert "end_time" not in body
    assert cog.bot.polls_api.update_polls.await_args.args[1] == 1234
    cog.start_poll.assert_awaited_once_with(42)


async def test_poll_start_with_duration_includes_end_time():
    cog = make_cog()
    poll_dict = cog.poll_dict(make_poll_model(published=False))
    cog.fetch_poll = AsyncMock(return_value=poll_dict)
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.bot.polls_api.update_polls = AsyncMock(return_value=[make_poll_model(published=False)])
    cog.start_poll = AsyncMock(return_value=[[poll_dict, MagicMock()]])

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_start(interaction, 42, duration=3600)

    body = cog.bot.polls_api.update_polls.await_args.args[0][0]
    assert body["end_time"] is not None
    parsed = datetime.fromisoformat(body["end_time"])
    assert timedelta(hours=1) >= (parsed - datetime.now(timezone.utc)) >= timedelta(minutes=59)


def make_threadless_guilds():
    guild = MagicMock()
    guild.get_channel_or_thread = MagicMock(return_value=None)
    cog_guild = MagicMock()
    cog_guild.id = 100
    guild.return_value = guild
    return [guild]


async def test_end_poll_natural_uses_lifecycle_endpoint():
    cog = make_cog()
    poll_dict = cog.poll_dict(make_poll_model())
    cog.fetch_poll = AsyncMock(return_value=poll_dict)
    cog.fetch_tag = AsyncMock(return_value=make_tag_dict())
    cog.fetch_guild_info = AsyncMock(return_value=make_guild_dict())
    cog.bot.polls_api.end_poll = AsyncMock(return_value=poll_dict)
    cog.schedule_ends = AsyncMock()
    cog.updatepollmessage = AsyncMock()
    cog.bot.get_channel = MagicMock(return_value=make_channel(300))
    cog.bot.get_guild = MagicMock(side_effect=lambda gid: MagicMock(get_channel_or_thread=MagicMock(return_value=None)))

    await cog.end_poll(42)

    cog.bot.polls_api.end_poll.assert_awaited_once_with(42)
    cog.updatepollmessage.assert_awaited_once()


async def test_end_poll_early_end_overwrites_end_time_via_update():
    cog = make_cog()
    poll_dict = cog.poll_dict(
        make_poll_model(end_time=datetime(2030, 1, 1, tzinfo=timezone.utc))
    )
    cog.fetch_poll = AsyncMock(return_value=poll_dict)
    cog.fetch_tag = AsyncMock(return_value=make_tag_dict())
    cog.fetch_guild_info = AsyncMock(return_value=make_guild_dict())
    cog.bot.polls_api.end_poll = AsyncMock()
    cog.bot.polls_api.update_polls = AsyncMock(return_value=[poll_dict])
    cog.schedule_ends = AsyncMock()
    cog.updatepollmessage = AsyncMock()
    cog.bot.get_channel = MagicMock(return_value=make_channel(300))
    cog.bot.get_guild = MagicMock(side_effect=lambda gid: MagicMock(get_channel_or_thread=MagicMock(return_value=None)))

    await cog.end_poll(42, end_now=True, user_id=1234)

    cog.bot.polls_api.end_poll.assert_not_awaited()
    cog.bot.polls_api.update_polls.assert_awaited_once()
    body = cog.bot.polls_api.update_polls.await_args.args[0][0]
    assert body["id"] == 42
    assert body["question"] == "Best hero?"
    assert body["choices"] == ["A", "B"]
    assert body["end_time"] is not None
    assert cog.bot.polls_api.update_polls.await_args.args[1] == 1234


async def test_poll_end_command_passes_user_for_early_end():
    cog = make_cog()
    poll_dict = cog.poll_dict(make_poll_model(active=True))
    cog.fetch_poll = AsyncMock(return_value=poll_dict)
    cog.has_manager_perms_by_user_and_ids = AsyncMock(return_value=[100])
    cog.end_poll = AsyncMock()

    interaction = MagicMock()
    interaction.user.id = 1234
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cog.poll_end(interaction, 42)

    cog.end_poll.assert_awaited_once_with(42, end_now=True, user_id=1234)


async def test_schedule_starts_fetches_unpublished_with_start_via_api():
    cog = make_cog()
    cog.guild_ids = [100]
    scheduled = make_poll_model(published=False)
    cog.bot.polls_api.sync_all_polls = AsyncMock(
        return_value=[scheduled, make_poll_model(id=2, published=True)]
    )
    created = []
    cog.bot.loop.create_task = lambda coro: (created.append(coro), coro.close())[1]

    await cog.schedule_starts()

    cog.bot.polls_api.sync_all_polls.assert_awaited_once()
    kwargs = cog.bot.polls_api.sync_all_polls.await_args.kwargs
    assert kwargs["guildId"] == 100
    assert kwargs["has_start"] == "true"
    assert len(created) == 1


async def test_schedule_ends_fetches_active_with_end_via_api():
    cog = make_cog()
    cog.guild_ids = [100]
    cog.bot.polls_api.sync_all_polls = AsyncMock(return_value=[])
    created = []
    cog.bot.loop.create_task = lambda coro: (created.append(coro), coro.close())[1]

    await cog.schedule_ends()

    kwargs = cog.bot.polls_api.sync_all_polls.await_args.kwargs
    assert kwargs["guildId"] == 100
    assert kwargs["has_end"] == "true"
    assert kwargs["active"] == "true"


def test_updatevotes_is_gone():
    assert not hasattr(PollsCog, "updatevotes")


async def test_do_update_poll_message_fetches_without_vote_recompute():
    cog = make_cog()
    poll_dict = cog.poll_dict(make_poll_model())
    cog.fetch_tag = AsyncMock(return_value=make_tag_dict())
    cog.fetch_poll = AsyncMock(return_value=poll_dict)
    cog.formatpollmessage = AsyncMock(return_value={"content": None, "embed": None, "view": None})
    cog.fetchpollmsg = AsyncMock(return_value=MagicMock(content=None, embeds=[], author=MagicMock(id=1)))
    cog.bot.updatemsg_lock = MagicMock()
    cog.bot.get_channel = MagicMock(return_value=MagicMock(fetch_message=AsyncMock()))
    cog.bot.user = MagicMock(id=2)

    await cog.do_update_poll_message(poll_dict)

    cog.fetch_poll.assert_awaited_with(42)
