import asyncio

import httpx2

from config import *
from funcs.polls_api_models import (
    GuildSettings,
    Poll,
    PollListResponse,
    Tag,
    VoteCounts,
)

RETRYABLE_STATUS = {502, 503, 504}
MAX_ATTEMPTS = 3
BACKOFF_SCHEDULE = [0.5, 1.0]
READ_TIMEOUT = 10.0
WRITE_TIMEOUT = 15.0

RETRY_SAFE = {
    "get_poll", "list_polls", "sync_polls", "get_tags", "get_tag",
    "get_guild", "get_guild_channels", "get_guild_roles",
    "cast_vote", "publish_poll", "end_poll",
    "update_polls", "delete_polls", "update_by_tag",
}


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

    async def _request(self, method, path, op_name, user_id=None, **kwargs) -> httpx2.Response:
        headers = self._headers(user_id)
        kwargs.setdefault("headers", {}).update(headers)
        attempts = MAX_ATTEMPTS if op_name in RETRY_SAFE else 1
        last_exc = None
        for attempt in range(attempts):
            try:
                response = await self._client.request(method, path, **kwargs)
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
        response = await self._request("GET", f"/polls/{poll_id}", "get_poll")
        return Poll.model_validate(response.json())

    async def list_polls(self, **params) -> PollListResponse:
        response = await self._request("GET", "/polls", "list_polls", params=params)
        return PollListResponse.model_validate(response.json())

    async def sync_polls(self, **params) -> PollListResponse:
        response = await self._request("GET", "/polls/sync", "sync_polls", params=params)
        return PollListResponse.model_validate(response.json())

    async def get_tags(self, **params) -> list[Tag]:
        response = await self._request("GET", "/tags", "get_tags", params=params)
        return [Tag.model_validate(item) for item in response.json()]

    async def get_tag(self, tag_id: int) -> Tag:
        response = await self._request("GET", f"/tags/{tag_id}", "get_tag")
        return Tag.model_validate(response.json())

    async def get_guild(self, guild_id: int) -> GuildSettings:
        response = await self._request("GET", f"/guilds/{guild_id}", "get_guild")
        return GuildSettings.model_validate(response.json())

    async def get_guild_channels(self, guild_id: int) -> list[dict]:
        response = await self._request("GET", f"/guilds/{guild_id}/channels", "get_guild_channels")
        return response.json()

    async def get_guild_roles(self, guild_id: int) -> list[dict]:
        response = await self._request("GET", f"/guilds/{guild_id}/roles", "get_guild_roles")
        return response.json()

    async def health(self) -> bool:
        try:
            response = await self._client.get("/health")
            return response.is_success
        except httpx2.HTTPError:
            return False

    # Vote (idempotent, auto-retry):

    async def cast_vote(self, poll_id: int, user_id: int, choice: int | None) -> VoteCounts:
        response = await self._request(
            "POST",
            f"/polls/{poll_id}/vote",
            "cast_vote",
            user_id=user_id,
            json={"user_id": user_id, "choice": choice},
        )
        return VoteCounts.model_validate(response.json())

    # Writes (user_id required for revalidation):

    async def create_polls(self, polls: list[dict], user_id: int) -> list[Poll]:
        response = await self._request("POST", "/polls", "create_polls", user_id=user_id, json=polls)
        return [Poll.model_validate(item) for item in response.json()]

    async def update_polls(self, polls: list[dict], user_id: int) -> list[Poll]:
        response = await self._request("PUT", "/polls", "update_polls", user_id=user_id, json=polls)
        return [Poll.model_validate(item) for item in response.json()]

    async def delete_polls(self, poll_ids: list[int], user_id: int) -> dict:
        response = await self._request(
            "DELETE", "/polls", "delete_polls", user_id=user_id, json={"ids": poll_ids}
        )
        return response.json()

    async def update_by_tag(self, tag: int, fields: dict, user_id: int) -> list[Poll]:
        response = await self._request(
            "PATCH", f"/tags/{tag}/polls", "update_by_tag", user_id=user_id, json=fields
        )
        return [Poll.model_validate(item) for item in response.json()]

    # Lifecycle (system ops — no user header):

    async def publish_poll(self, poll_id: int, message_id: int, crosspost_ids: list[int]) -> Poll:
        response = await self._request(
            "POST",
            f"/polls/{poll_id}/publish",
            "publish_poll",
            json={"message_id": message_id, "crosspost_message_ids": crosspost_ids},
        )
        return Poll.model_validate(response.json())

    async def end_poll(self, poll_id: int) -> Poll:
        response = await self._request("POST", f"/polls/{poll_id}/end", "end_poll")
        return Poll.model_validate(response.json())

    async def crosspost_poll(self, poll_id: int, message_id: int) -> Poll:
        response = await self._request(
            "POST",
            f"/polls/{poll_id}/crosspost",
            "crosspost_poll",
            json={"message_id": message_id},
        )
        return Poll.model_validate(response.json())

    async def close(self):
        await self._client.aclose()


async def setup(bot):
    bot.polls_api = PollsAPIClient(polls_api_base_url, polls_api_token)


async def teardown(bot):
    await bot.polls_api.close()
