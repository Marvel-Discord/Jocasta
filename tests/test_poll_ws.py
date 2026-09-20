import asyncio
import json
import time

import websockets

import funcs.poll_ws as poll_ws
from funcs.poll_ws import PollWebSocketClient

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
