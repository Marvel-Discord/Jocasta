import asyncio
import json
import time

import websockets

from funcs.polls_api_models import BotEventFrame

DEBOUNCE_SECONDS = 1.0
RECONNECT_BACKOFF_INITIAL = 1.0
RECONNECT_BACKOFF_MAX = 60.0
DEBOUNCE_CHECK_INTERVAL = 0.25


def ws_url_from_base(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.startswith("https://"):
        return base.replace("https://", "wss://", 1) + "/bot/events"
    return base.replace("http://", "ws://", 1) + "/bot/events"


class PollWebSocketClient:
    def __init__(self, api_client, on_poll_update, on_full_resync):
        """on_poll_update(poll_id) — called after the debounce window expires for a poll.
        on_full_resync() — called after every successful (re)connect."""
        self.api_client = api_client
        self.on_poll_update = on_poll_update
        self.on_full_resync = on_full_resync
        self._running = False
        self._dirty: dict[int, float] = {}
        self._debounce_task = None

    async def start(self, ws_url: str, token: str):
        self._running = True
        self._debounce_task = asyncio.create_task(self._debounce_loop())

        backoff = RECONNECT_BACKOFF_INITIAL
        while self._running:
            try:
                async with websockets.connect(
                    ws_url,
                    additional_headers={"Authorization": f"Bearer {token}"},
                ) as ws:
                    hello = json.loads(await ws.recv())
                    if hello.get("type") != "connected":
                        raise ConnectionError("Unexpected handshake")
                    await self.on_full_resync()
                    backoff = RECONNECT_BACKOFF_INITIAL
                    async for message in ws:
                        try:
                            frame = BotEventFrame.model_validate_json(message)
                        except Exception as e:
                            print(f"[PollWS] Discarding malformed frame: {e}")
                            continue
                        self._dirty[frame.id] = time.monotonic()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if not self._running:
                    break
                print(f"[PollWS] Disconnected: {e}; reconnect in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX)

    async def stop(self):
        self._running = False
        if self._debounce_task:
            self._debounce_task.cancel()

    async def _debounce_loop(self):
        while True:
            await asyncio.sleep(DEBOUNCE_CHECK_INTERVAL)
            now = time.monotonic()
            expired = [pid for pid, ts in self._dirty.items() if now - ts >= DEBOUNCE_SECONDS]
            for poll_id in expired:
                del self._dirty[poll_id]
                try:
                    await self.on_poll_update(poll_id)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    print(f"[PollWS] Handler error for poll {poll_id}: {e}")
