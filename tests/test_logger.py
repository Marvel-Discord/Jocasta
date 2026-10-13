"""Tests for the loguru setup + stdlib bridge."""
import logging

from loguru import logger

from funcs.logger import InterceptHandler


def test_intercept_handler_routes_stdlib_into_loguru():
    records: list[dict] = []
    sink_id = logger.add(
        lambda msg: records.append(msg.record),
        level="DEBUG",
    )
    try:
        record = logging.LogRecord(
            name="discord.gateway",
            level=logging.DEBUG,
            pathname=__file__,
            lineno=1,
            msg="shard connected to %s",
            args=("session-1",),
            exc_info=None,
        )
        InterceptHandler().emit(record)
    finally:
        logger.remove(sink_id)

    match = next(r for r in records if "shard connected" in str(r["message"]))
    assert match["level"].name == "DEBUG"
    assert str(match["message"]) == "shard connected to session-1"
    # Attribution: the record must point at THIS test's call site, not at
    # InterceptHandler.emit (the frame-walk must not be dead code).
    assert match["function"] == "test_intercept_handler_routes_stdlib_into_loguru"


def test_intercept_handler_maps_warning_level():
    messages: list[tuple[str, str]] = []
    sink_id = logger.add(
        lambda msg: messages.append((msg.record["level"].name, str(msg.record["message"]))),
        level="DEBUG",
    )
    try:
        record = logging.LogRecord(
            name="redis",
            level=logging.WARNING,
            pathname=__file__,
            lineno=2,
            msg="connection pool exhausted",
            args=(),
            exc_info=None,
        )
        InterceptHandler().emit(record)
    finally:
        logger.remove(sink_id)

    assert ("WARNING", "connection pool exhausted") in messages


def test_tracebacks_render_without_frame_locals():
    """Security pin: bridged exceptions walk up to Client.run whose source
    line references the TOKEN local — better-exceptions (diagnose) renders
    that line with the variable's VALUE substituted, leaking the token into
    container logs. The sink must render plain source lines instead
    (diagnose/backtrace off)."""
    from funcs.logger import SINK_OPTIONS

    output: list[str] = []
    sink_options = {k: v for k, v in SINK_OPTIONS.items() if k != "level"}
    sink_id = logger.add(
        lambda msg: output.append(str(msg)), level="DEBUG", **sink_options
    )

    secret_local = "TOPSECRET-TOKEN-VALUE"

    def run(token):
        raise ValueError("boom")

    try:
        run(secret_local)  # this caller line references the secret local
    except ValueError:
        logger.exception("caught")
    finally:
        logger.remove(sink_id)

    joined = "".join(output)
    assert "ValueError: boom" in joined  # traceback still present
    assert "run(secret_local)" in joined  # source line shown verbatim
    assert "TOPSECRET-TOKEN-VALUE" not in joined  # value never substituted
