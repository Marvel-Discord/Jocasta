import asyncio
from enum import StrEnum, auto

import httpx2
from discord.ext import commands

from config import *
from funcs.polls_api_models import (
    GuildSettings,
    Poll,
    PollListResponse,
    Tag,
    VoteCounts,
)

MAX_ATTEMPTS = 3
BACKOFF_SCHEDULE = [0.5, 1.0]
RETRYABLE_STATUS = {502, 503, 504}
READ_TIMEOUT = 10.0
WRITE_TIMEOUT = 15.0


class Op(StrEnum):
    GET_POLL = auto()
    LIST_POLLS = auto()
    SYNC_POLLS = auto()
    GET_TAGS = auto()
    GET_TAG = auto()
    GET_GUILD = auto()
    GET_GUILD_CHANNELS = auto()
    GET_GUILD_ROLES = auto()
    HEALTH = auto()
    CAST_VOTE = auto()
    CREATE_POLLS = auto()
    UPDATE_POLLS = auto()
    DELETE_POLLS = auto()
    UPDATE_BY_TAG = auto()
    PUBLISH_POLL = auto()
    END_POLL = auto()
    CROSSPOST_POLL = auto()


RETRY_SAFE = frozenset({
    Op.GET_POLL, Op.LIST_POLLS, Op.SYNC_POLLS, Op.GET_TAGS, Op.GET_TAG,
    Op.GET_GUILD, Op.GET_GUILD_CHANNELS, Op.GET_GUILD_ROLES,
    Op.CAST_VOTE, Op.PUBLISH_POLL, Op.END_POLL,
    Op.UPDATE_POLLS, Op.DELETE_POLLS, Op.UPDATE_BY_TAG,
})

READ_OPS = frozenset({
    Op.GET_POLL, Op.LIST_POLLS, Op.SYNC_POLLS, Op.GET_TAGS, Op.GET_TAG,
    Op.GET_GUILD, Op.GET_GUILD_CHANNELS, Op.GET_GUILD_ROLES, Op.HEALTH,
})


class PollsAPIError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"API {status}: {message}")


def _error_message(response: httpx2.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            return data.get("detail") or data.get("message") or response.text
    except ValueError:
        pass
    return response.text


class PollsAPIClient:
    def __init__(self, base_url: str, token: str, transport: httpx2.AsyncBaseTransport | None = None):
        self._client = httpx2.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx2.Timeout(WRITE_TIMEOUT, connect=5.0),
            transport=transport,
        )

    def _headers(self, user_id: int | None) -> dict:
        if user_id is None:
            return {}
        return {"X-Discord-User-Id": str(user_id)}

    async def _request(self, method, path, op, user_id=None, **kwargs) -> httpx2.Response:
        headers = self._headers(user_id)
        kwargs.setdefault("headers", {}).update(headers)
        timeout = READ_TIMEOUT if op in READ_OPS else WRITE_TIMEOUT
        attempts = MAX_ATTEMPTS if op in RETRY_SAFE else 1
        last_exc = None
        for attempt in range(attempts):
            try:
                response = await self._client.request(method, path, timeout=timeout, **kwargs)
            except httpx2.HTTPError as e:
                last_exc = e
                if attempt + 1 < attempts:
                    await asyncio.sleep(BACKOFF_SCHEDULE[min(attempt, len(BACKOFF_SCHEDULE) - 1)])
                    continue
                raise PollsAPIError(0, f"network error: {e}") from e
            if response.status_code in RETRYABLE_STATUS and attempt + 1 < attempts:
                await asyncio.sleep(BACKOFF_SCHEDULE[min(attempt, len(BACKOFF_SCHEDULE) - 1)])
                continue
            if response.is_error:
                raise PollsAPIError(response.status_code, _error_message(response))
            return response
        raise PollsAPIError(0, f"network error: {last_exc}")

    # Read ops (auto-retry):

    async def get_poll(self, poll_id: int) -> Poll:
        response = await self._request("GET", f"/bot/polls/{poll_id}", Op.GET_POLL)
        return Poll.model_validate(response.json())

    async def list_polls(self, **params) -> PollListResponse:
        response = await self._request("GET", "/bot/polls", Op.LIST_POLLS, params=params)
        return PollListResponse.model_validate(response.json())

    async def sync_polls(self, **params) -> PollListResponse:
        response = await self._request("GET", "/bot/polls/sync", Op.SYNC_POLLS, params=params)
        return PollListResponse.model_validate(response.json())

    async def get_tags(self, **params) -> list[Tag]:
        response = await self._request("GET", "/bot/tags", Op.GET_TAGS, params=params)
        return [Tag.model_validate(item) for item in response.json()]

    async def get_tag(self, tag_id: int) -> Tag:
        response = await self._request("GET", f"/bot/tags/{tag_id}", Op.GET_TAG)
        return Tag.model_validate(response.json())

    async def get_guild(self, guild_id: int) -> GuildSettings:
        response = await self._request("GET", f"/bot/guilds/{guild_id}", Op.GET_GUILD)
        return GuildSettings.model_validate(response.json())

    async def get_guild_channels(self, guild_id: int) -> list[dict]:
        response = await self._request("GET", f"/bot/discord/guilds/{guild_id}/channels", Op.GET_GUILD_CHANNELS)
        return response.json()

    async def get_guild_roles(self, guild_id: int) -> list[dict]:
        response = await self._request("GET", f"/bot/discord/guilds/{guild_id}/roles", Op.GET_GUILD_ROLES)
        return response.json()

    async def health(self) -> bool:
        try:
            response = await self._client.get("/health")
            return response.is_success
        except httpx2.HTTPError:
            return False

    # Vote (idempotent, auto-retry; user id travels in the header only):

    async def cast_vote(self, poll_id: int, user_id: int, choice: int | None) -> VoteCounts:
        response = await self._request(
            "POST",
            f"/bot/polls/{poll_id}/vote",
            Op.CAST_VOTE,
            user_id=user_id,
            json={"choice": choice},
        )
        return VoteCounts.model_validate(response.json())

    # Writes (user_id required for revalidation):

    async def create_polls(self, polls: list[dict], user_id: int) -> list[Poll]:
        response = await self._request(
            "POST", "/bot/polls/create", Op.CREATE_POLLS, user_id=user_id, json=polls
        )
        return [Poll.model_validate(item) for item in response.json()["polls"]]

    async def update_polls(self, polls: list[dict], user_id: int) -> list[Poll]:
        response = await self._request(
            "POST", "/bot/polls/update", Op.UPDATE_POLLS, user_id=user_id, json=polls
        )
        return [Poll.model_validate(item) for item in response.json()["polls"]]

    async def delete_polls(self, poll_ids: list[int], user_id: int) -> dict:
        response = await self._request(
            "POST", "/bot/polls/delete", Op.DELETE_POLLS, user_id=user_id, json={"pollIds": poll_ids}
        )
        return response.json()

    async def update_by_tag(self, tag: int, fields: dict, user_id: int) -> list[Poll]:
        response = await self._request(
            "POST",
            "/bot/polls/update-by-tag",
            Op.UPDATE_BY_TAG,
            user_id=user_id,
            json={"tag": tag, **fields},
        )
        return [Poll.model_validate(item) for item in response.json()["polls"]]

    # Lifecycle (system ops — no user header):

    async def publish_poll(self, poll_id: int, message_id: int, crosspost_ids: list[int]) -> Poll:
        response = await self._request(
            "POST",
            f"/bot/polls/{poll_id}/publish",
            Op.PUBLISH_POLL,
            json={"message_id": message_id, "crosspost_message_ids": crosspost_ids},
        )
        return Poll.model_validate(response.json())

    async def end_poll(self, poll_id: int) -> Poll:
        response = await self._request("POST", f"/bot/polls/{poll_id}/end", Op.END_POLL)
        return Poll.model_validate(response.json())

    async def crosspost_poll(self, poll_id: int, message_id: int) -> Poll:
        response = await self._request(
            "POST",
            f"/bot/polls/{poll_id}/crosspost",
            Op.CROSSPOST_POLL,
            json={"message_id": message_id},
        )
        return Poll.model_validate(response.json())

    async def close(self):
        await self._client.aclose()


class PollsAPICog(commands.Cog, name="PollsAPI"):
    """Manages the bot's polls API client and exposes it as `bot.polls_api`."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.polls_api = PollsAPIClient(polls_api_base_url, polls_api_token)

    async def cog_unload(self):
        if self.bot.polls_api:
            await self.bot.polls_api.close()


async def setup(bot):
    await bot.add_cog(PollsAPICog(bot))
