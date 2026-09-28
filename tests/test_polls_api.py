import json
from unittest.mock import AsyncMock, MagicMock

import httpx2
import pytest
from pydantic import ValidationError

import funcs.polls_api as polls_api
from funcs.polls_api import PollsAPIClient, PollsAPICog, PollsAPIError
from funcs.polls_api_models import Poll, PollListResponse, Tag, VoteCounts


def poll_payload(**overrides) -> dict:
    payload = {
        "id": 1,
        "question": "Best Avenger?",
        "published": False,
        "active": True,
        "guild_id": 100,
        "choices": ["Iron Man", "Captain America"],
        "votes": [3, 2],
        "total_votes": 5,
        "time": None,
        "start_time": "2026-01-01T12:00:00Z",
        "end_time": None,
        "num": 7,
        "message_id": None,
        "crosspost_message_ids": [],
        "tag": 1,
        "image": None,
        "description": None,
        "thread_question": None,
        "show_question": True,
        "show_options": True,
        "show_voting": True,
        "fallback": False,
    }
    payload.update(overrides)
    return payload


def tag_payload(**overrides) -> dict:
    payload = {
        "tag": 1,
        "name": "comics",
        "guild_id": 100,
        "channel_id": 200,
        "crosspost_channels": [],
        "crosspost_servers": [],
        "current_num": None,
        "colour": None,
        "end_message": None,
        "end_message_latest_ids": [],
        "end_message_replace": False,
        "end_message_role_ids": [],
        "end_message_ping": False,
        "end_message_self_assign": False,
        "persistent": False,
    }
    payload.update(overrides)
    return payload


def make_client(handler) -> PollsAPIClient:
    return PollsAPIClient(
        "http://test",
        "test-token",
        transport=httpx2.MockTransport(handler),
    )


async def test_get_poll_returns_validated_poll():
    async def handler(request):
        assert request.url.path == "/bot/polls/5"
        return httpx2.Response(200, json=poll_payload(id=5, question="Hi"))

    client = make_client(handler)
    poll = await client.get_poll(5)
    assert isinstance(poll, Poll)
    assert poll.id == 5
    assert poll.question == "Hi"
    assert poll.votes == [3, 2]
    assert poll.start_time is not None


async def test_cast_vote_returns_vote_counts():
    seen = {}

    async def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json={"votes": [1, 2, 0], "total_votes": 3})

    client = make_client(handler)
    counts = await client.cast_vote(1, 42, 0)
    assert isinstance(counts, VoteCounts)
    assert counts.votes == [1, 2, 0]
    assert counts.total_votes == 3
    assert seen["path"] == "/bot/polls/1/vote"
    assert seen["body"] == {"choice": 0}


async def test_votes_null_raises_validation_error():
    async def handler(request):
        return httpx2.Response(200, json=poll_payload(votes=None))

    client = make_client(handler)
    with pytest.raises(ValidationError):
        await client.get_poll(1)


async def test_list_polls_returns_poll_list_response():
    async def handler(request):
        return httpx2.Response(
            200,
            json={"data": [poll_payload(id=1), poll_payload(id=2)], "meta": {"total": 2}},
        )

    client = make_client(handler)
    result = await client.list_polls(tag=1)
    assert isinstance(result, PollListResponse)
    assert [p.id for p in result.data] == [1, 2]
    assert result.meta == {"total": 2}


async def test_get_tags_returns_list_of_tags():
    async def handler(request):
        return httpx2.Response(200, json=[tag_payload(tag=1), tag_payload(tag=2, name="movies")])

    client = make_client(handler)
    tags = await client.get_tags(guild_id=100)
    assert len(tags) == 2
    assert all(isinstance(t, Tag) for t in tags)
    assert tags[1].name == "movies"


async def test_400_raises_polls_api_error_without_retry():
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx2.Response(400, json={"detail": "bad request"})

    client = make_client(handler)
    with pytest.raises(PollsAPIError) as exc_info:
        await client.get_poll(1)
    assert exc_info.value.status == 400
    assert "bad request" in exc_info.value.message
    assert len(calls) == 1


async def test_404_raises_polls_api_error():
    async def handler(request):
        return httpx2.Response(404, json={"detail": "not found"})

    client = make_client(handler)
    with pytest.raises(PollsAPIError) as exc_info:
        await client.get_poll(99)
    assert exc_info.value.status == 404


async def test_503_retry_safe_op_is_retried(monkeypatch):
    monkeypatch.setattr(polls_api, "BACKOFF_SCHEDULE", [0, 0])
    calls = []

    async def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx2.Response(503, json={"detail": "unavailable"})
        return httpx2.Response(200, json=poll_payload())

    client = make_client(handler)
    poll = await client.get_poll(1)
    assert isinstance(poll, Poll)
    assert len(calls) == 2


async def test_503_exhausts_after_max_attempts(monkeypatch):
    monkeypatch.setattr(polls_api, "BACKOFF_SCHEDULE", [0, 0])
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx2.Response(503, json={"detail": "unavailable"})

    client = make_client(handler)
    with pytest.raises(PollsAPIError) as exc_info:
        await client.get_poll(1)
    assert exc_info.value.status == 503
    assert len(calls) == 3


async def test_503_create_polls_is_not_retried(monkeypatch):
    monkeypatch.setattr(polls_api, "BACKOFF_SCHEDULE", [0, 0])
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx2.Response(503, json={"detail": "unavailable"})

    client = make_client(handler)
    with pytest.raises(PollsAPIError) as exc_info:
        await client.create_polls([poll_payload()], user_id=42)
    assert exc_info.value.status == 503
    assert len(calls) == 1


async def test_503_crosspost_poll_is_not_retried(monkeypatch):
    monkeypatch.setattr(polls_api, "BACKOFF_SCHEDULE", [0, 0])
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx2.Response(503, json={"detail": "unavailable"})

    client = make_client(handler)
    with pytest.raises(PollsAPIError) as exc_info:
        await client.crosspost_poll(1, 555)
    assert exc_info.value.status == 503
    assert len(calls) == 1


async def test_network_error_retry_safe_op_is_retried(monkeypatch):
    monkeypatch.setattr(polls_api, "BACKOFF_SCHEDULE", [0, 0])
    calls = []

    async def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx2.ConnectError("connection refused")
        return httpx2.Response(200, json=poll_payload())

    client = make_client(handler)
    poll = await client.get_poll(1)
    assert isinstance(poll, Poll)
    assert len(calls) == 2


async def test_network_error_exhausted_raises_polls_api_error(monkeypatch):
    monkeypatch.setattr(polls_api, "BACKOFF_SCHEDULE", [0, 0])
    calls = []

    async def handler(request):
        calls.append(request)
        raise httpx2.ConnectError("connection refused")

    client = make_client(handler)
    with pytest.raises(PollsAPIError) as exc_info:
        await client.get_poll(1)
    assert exc_info.value.status == 0
    assert len(calls) == 3


async def test_user_id_header_present_when_given():
    seen = {}

    async def handler(request):
        seen.update({k.lower(): v for k, v in request.headers.items()})
        return httpx2.Response(200, json={"votes": [1], "total_votes": 1})

    client = make_client(handler)
    await client.cast_vote(1, 42, 0)
    assert seen["x-discord-user-id"] == "42"
    assert seen["authorization"] == "Bearer test-token"


async def test_user_id_header_absent_when_none():
    seen = {}

    async def handler(request):
        seen.update({k.lower(): v for k, v in request.headers.items()})
        return httpx2.Response(200, json=poll_payload())

    client = make_client(handler)
    await client.get_poll(1)
    assert "x-discord-user-id" not in seen
    assert seen["authorization"] == "Bearer test-token"


async def test_authorization_header_on_every_request():
    auth_values = []

    async def handler(request):
        auth_values.append(request.headers["Authorization"])
        return httpx2.Response(200, json=poll_payload())

    client = make_client(handler)
    await client.get_poll(1)
    await client.end_poll(1)
    await client.publish_poll(1, 555, [])
    assert auth_values == ["Bearer test-token"] * 3


async def test_create_polls_posts_wrapped_body_and_parses_polls():
    seen = {}

    async def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            201, json={"message": "Polls created successfully", "polls": [poll_payload(id=9)]}
        )

    client = make_client(handler)
    polls = await client.create_polls([poll_payload()], user_id=42)
    assert seen["path"] == "/bot/polls/create"
    assert seen["body"] == [poll_payload()]
    assert [p.id for p in polls] == [9]
    assert all(isinstance(p, Poll) for p in polls)


async def test_update_polls_posts_wrapped_body_and_parses_polls():
    seen = {}

    async def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            200, json={"message": "Polls updated successfully", "polls": [poll_payload(id=1, question="Updated")]}
        )

    client = make_client(handler)
    polls = await client.update_polls([poll_payload(id=1)], user_id=42)
    assert seen["path"] == "/bot/polls/update"
    assert seen["body"] == [poll_payload(id=1)]
    assert [p.question for p in polls] == ["Updated"]


async def test_delete_polls_posts_poll_ids():
    seen = {}

    async def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json={"message": "Polls deleted successfully", "deletedCount": 2})

    client = make_client(handler)
    result = await client.delete_polls([1, 2], user_id=42)
    assert seen["path"] == "/bot/polls/delete"
    assert seen["body"] == {"pollIds": [1, 2]}
    assert result == {"message": "Polls deleted successfully", "deletedCount": 2}


async def test_update_by_tag_posts_tag_and_fields():
    seen = {}

    async def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            200, json={"message": "Polls updated successfully", "polls": [poll_payload(tag=3, question="New")]}
        )

    client = make_client(handler)
    polls = await client.update_by_tag(3, {"question": "New"}, user_id=42)
    assert seen["path"] == "/bot/polls/update-by-tag"
    assert seen["body"] == {"tag": 3, "question": "New"}
    assert [p.question for p in polls] == ["New"]


async def test_get_guild_channels_uses_discord_proxy_path():
    async def handler(request):
        assert request.url.path == "/bot/discord/guilds/100/channels"
        return httpx2.Response(200, json=[{"id": "5", "name": "general"}])

    client = make_client(handler)
    channels = await client.get_guild_channels(100)
    assert channels == [{"id": "5", "name": "general"}]


async def test_cog_load_exposes_bot_polls_api():
    bot = MagicMock()
    cog = PollsAPICog(bot)
    await cog.cog_load()
    assert isinstance(bot.polls_api, PollsAPIClient)
    await bot.polls_api.close()


async def test_cog_unload_closes_client():
    bot = MagicMock()
    client = MagicMock()
    client.close = AsyncMock()
    bot.polls_api = client
    cog = PollsAPICog(bot)
    await cog.cog_unload()
    client.close.assert_awaited_once()


def user_vote_payload(**overrides) -> dict:
    payload = {
        "id": 123400042,
        "user_id": "1234",
        "poll_id": 42,
        "choice": 1,
    }
    payload.update(overrides)
    return payload


async def test_get_user_votes_returns_validated_votes():
    async def handler(request):
        assert request.url.path == "/bot/polls/votes/1234"
        return httpx2.Response(
            200,
            json=[user_vote_payload(), user_vote_payload(id="223400043", user_id="1234", poll_id=43, choice=0)],
        )

    client = make_client(handler)
    votes = await client.get_user_votes(1234)
    assert len(votes) == 2
    assert votes[0].poll_id == 42
    assert votes[0].choice == 1
    assert votes[1].user_id == 1234


async def test_sync_all_polls_pages_until_total():
    pages = {
        1: httpx2.Response(200, json={"data": [poll_payload(id=i) for i in range(1, 101)], "meta": {"total": 120, "page": 1, "limit": 100}}),
        2: httpx2.Response(200, json={"data": [poll_payload(id=i) for i in range(101, 121)], "meta": {"total": 120, "page": 2, "limit": 100}}),
    }
    seen = []

    async def handler(request):
        seen.append(dict(request.url.params))
        return pages[int(request.url.params["page"])]

    client = make_client(handler)
    polls = await client.sync_all_polls(100, tag=3)
    assert len(polls) == 120
    assert seen[0]["guildId"] == "100"
    assert seen[0]["tag"] == "3"
    assert len(seen) == 2


async def test_sync_all_polls_stops_on_empty_page():
    async def handler(request):
        return httpx2.Response(200, json={"data": [], "meta": {"total": 0}})

    client = make_client(handler)
    assert await client.sync_all_polls(100) == []


async def test_sync_all_polls_translates_positional_guild_id_to_guildid_param():
    seen = []

    async def handler(request):
        seen.append(dict(request.url.params))
        return httpx2.Response(
            200,
            json={"data": [poll_payload()], "meta": {"total": 1, "page": 1, "limit": 100}},
        )

    client = make_client(handler)
    polls = await client.sync_all_polls(100, has_start="true", active="true")
    assert len(polls) == 1
    assert len(seen) == 1
    assert seen[0]["guildId"] == "100"
    assert seen[0]["has_start"] == "true"
    assert seen[0]["active"] == "true"
