import asyncio
import json
import time

import websockets

import funcs.poll_ws as poll_ws
from funcs.poll_ws import PollWebSocketClient, ws_url_from_base

HELLO = json.dumps({"type": "connected"})


def frame(poll_id: int) -> str:
    return json.dumps({"table": "polls", "operation": "UPDATE", "id": poll_id})


class FakeWS:
    """Async-context-manager WS stand-in: recv() pops the hello frame,
    async iteration yields the rest, then raises to simulate disconnect."""

    def __init__(self, messages):
        self._messages = list(messages)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def recv(self):
        return self._messages.pop(0)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise ConnectionError("connection closed by server")
        return self._messages.pop(0)


class HeldOpenWS(FakeWS):
    """FakeWS that blocks (instead of raising) once its messages are drained,
    so the test controls when the connection ends."""

    def __init__(self, messages):
        super().__init__(messages)
        self.release = asyncio.Event()

    async def __anext__(self):
        if self._messages:
            return self._messages.pop(0)
        await self.release.wait()
        raise ConnectionError("connection closed by server")


def make_connect(script):
    """Returns (fake_connect, calls). Each connect() call takes the next
    scripted step (a FakeWS to yield, or an exception to raise); the last
    step repeats forever. Mirrors websockets>=13: connect() is a plain
    call returning an async context manager."""
    calls = []

    def fake_connect(url, **kwargs):
        calls.append(url)
        step = script[min(len(calls) - 1, len(script) - 1)]
        if isinstance(step, BaseException):
            raise step
        return step

    return fake_connect, calls


def make_ws_client(monkeypatch, script):
    updates = []
    resyncs = []

    async def on_poll_update(poll_id):
        updates.append(poll_id)

    async def on_full_resync():
        resyncs.append(True)

    client = PollWebSocketClient(None, on_poll_update, on_full_resync)
    fake_connect, calls = make_connect(script)
    monkeypatch.setattr(websockets, "connect", fake_connect)
    monkeypatch.setattr(poll_ws, "DEBOUNCE_SECONDS", 0.05)
    monkeypatch.setattr(poll_ws, "DEBOUNCE_CHECK_INTERVAL", 0.01)
    monkeypatch.setattr(poll_ws, "RECONNECT_BACKOFF_INITIAL", 0.01)
    monkeypatch.setattr(poll_ws, "RECONNECT_BACKOFF_MAX", 0.02)
    return client, updates, resyncs, calls


async def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out waiting for condition"
        await asyncio.sleep(0.01)


async def run_and_stop(client):
    task = asyncio.create_task(client.start("ws://test", "test-token"))
    try:
        yield task
    finally:
        await client.stop()
        await asyncio.wait_for(task, timeout=2.0)


async def test_handshake_calls_full_resync(monkeypatch):
    client, updates, resyncs, calls = make_ws_client(
        monkeypatch, [FakeWS([HELLO]), OSError("down")]
    )
    async for task in run_and_stop(client):
        await wait_until(lambda: len(resyncs) >= 1)
        assert calls[0] == "ws://test"


async def test_same_poll_frames_within_window_debounce_to_one_update(monkeypatch):
    client, updates, resyncs, calls = make_ws_client(
        monkeypatch, [FakeWS([HELLO, frame(42), frame(42)]), OSError("down")]
    )
    async for task in run_and_stop(client):
        await wait_until(lambda: len(updates) >= 1)
        await asyncio.sleep(0.2)
        assert updates == [42]


async def test_different_polls_each_get_their_own_update(monkeypatch):
    client, updates, resyncs, calls = make_ws_client(
        monkeypatch, [FakeWS([HELLO, frame(42), frame(7)]), OSError("down")]
    )
    async for task in run_and_stop(client):
        await wait_until(lambda: len(updates) >= 2)
        assert sorted(updates) == [7, 42]


async def test_disconnect_then_reconnect_resyncs_again(monkeypatch):
    client, updates, resyncs, calls = make_ws_client(
        monkeypatch,
        [OSError("boom"), FakeWS([HELLO]), OSError("down"), FakeWS([HELLO]), OSError("down")],
    )
    async for task in run_and_stop(client):
        await wait_until(lambda: len(resyncs) >= 2)
        assert len(calls) >= 4


async def test_resync_failure_grows_backoff_and_success_resets_it(monkeypatch):
    client, updates, resyncs, calls = make_ws_client(
        monkeypatch, [FakeWS([HELLO]), FakeWS([HELLO]), OSError("down")]
    )
    monkeypatch.setattr(poll_ws, "RECONNECT_BACKOFF_INITIAL", 0.08)
    monkeypatch.setattr(poll_ws, "RECONNECT_BACKOFF_MAX", 0.4)

    real_sleep = asyncio.sleep
    sleeps = []

    async def recording_sleep(delay):
        sleeps.append(delay)
        await real_sleep(delay)

    monkeypatch.setattr(asyncio, "sleep", recording_sleep)

    resync_calls = []

    async def flaky_resync():
        resync_calls.append(True)
        if len(resync_calls) == 1:
            raise RuntimeError("api down during resync")

    client.on_full_resync = flaky_resync

    async for task in run_and_stop(client):
        await wait_until(lambda: len(calls) >= 3, timeout=5.0)

    reconnect_sleeps = [d for d in sleeps if d >= 0.05]
    # sleep 1: resync failed on a healthy connection -> initial backoff
    # sleep 2: resync succeeded then WS closed -> backoff was reset, not grown
    # sleep 3: plain connect failure -> grown from the reset value
    assert reconnect_sleeps[:3] == [0.08, 0.08, 0.16]


async def test_malformed_frame_is_discarded_and_connection_survives(monkeypatch):
    ws = HeldOpenWS([HELLO, "not json{{", '{"table": "polls"}', frame(42)])
    client, updates, resyncs, calls = make_ws_client(
        monkeypatch, [ws, OSError("down")]
    )
    task = asyncio.create_task(client.start("ws://test", "test-token"))
    try:
        await wait_until(lambda: updates == [42])
        assert len(calls) == 1
    finally:
        ws.release.set()
        await client.stop()
        await asyncio.wait_for(task, timeout=2.0)


async def test_stop_cancels_debounce_loop_and_exits_start(monkeypatch):
    client, updates, resyncs, calls = make_ws_client(
        monkeypatch, [FakeWS([HELLO]), OSError("down")]
    )
    task = asyncio.create_task(client.start("ws://test", "test-token"))
    try:
        await wait_until(lambda: len(resyncs) >= 1)
        await client.stop()
        assert client._running is False
        await asyncio.wait_for(task, timeout=2.0)
        await asyncio.sleep(0.05)
        assert client._debounce_task.cancelled()
    finally:
        await client.stop()
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.TimeoutError:
            task.cancel()


def test_ws_url_from_base_http():
    assert ws_url_from_base("http://localhost:8000/api/v1") == "ws://localhost:8000/api/v1/bot/events"


def test_ws_url_from_base_https():
    assert ws_url_from_base("https://polls.example.com/api/v1") == "wss://polls.example.com/api/v1/bot/events"


def test_ws_url_from_base_strips_trailing_slash():
    assert ws_url_from_base("http://localhost:8000/api/v1/") == "ws://localhost:8000/api/v1/bot/events"


async def test_debounce_loop_survives_handler_exception(monkeypatch):
    monkeypatch.setattr(poll_ws, "DEBOUNCE_SECONDS", 0.05)
    monkeypatch.setattr(poll_ws, "DEBOUNCE_CHECK_INTERVAL", 0.02)

    calls = []

    async def flaky_first(poll_id):
        calls.append(("boom", poll_id))
        raise RuntimeError("handler exploded")

    client = PollWebSocketClient(None, flaky_first, None)
    task = asyncio.create_task(client._debounce_loop())

    client._dirty[42] = time.monotonic() - 1
    try:
        await wait_until(lambda: ("boom", 42) in calls)
        assert 42 not in client._dirty

        async def recovered(poll_id):
            calls.append(("ok", poll_id))

        client.on_poll_update = recovered
        client._dirty[42] = time.monotonic() - 1
        await wait_until(lambda: ("ok", 42) in calls)
        assert not task.done()
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
