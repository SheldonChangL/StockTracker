"""Tests for the subprocess AI pipe (Story 5.3, AC-1..AC-3)."""

from __future__ import annotations

import io

import pytest

from tsic.ai.pipe import read_payload, resolve_agent_command, run


def _echo_runner() -> tuple[list, callable]:
    """A fake runner echoing stdin, recording the argv it was called with (AC-1).

    Returns the capture list (filled with the argv) and the runner itself so a
    test can assert both the returned stdout and how the command was parsed.
    """
    captured: list = []

    def runner(argv: list[str], payload: str) -> str:
        captured.append(argv)
        return payload  # echo stdin straight back, like ``cat``

    return captured, runner


# AC-1: payload is fed on stdin and the agent's stdout is returned verbatim.
def test_run_feeds_stdin_and_returns_stdout() -> None:
    captured, runner = _echo_runner()
    out = run("cat", "hello payload", runner=runner)
    assert out == "hello payload"
    assert captured == [["cat"]]


# AC-1 corollary: a multi-word command is split into argv, not run as one token.
def test_run_splits_command_into_argv() -> None:
    captured, runner = _echo_runner()
    run("ollama run llama3", "data", runner=runner)
    assert captured == [["ollama", "run", "llama3"]]


# AC-1 guard: an empty command has nothing to run and is rejected.
def test_run_rejects_empty_command() -> None:
    _, runner = _echo_runner()
    with pytest.raises(ValueError):
        run("   ", "data", runner=runner)


# AC-2: an explicit --agent override is used instead of auto-detection.
def test_resolve_uses_agent_override() -> None:
    # probe reports claude is installed, but the override must still win.
    assert (
        resolve_agent_command("ollama run llama3", probe=lambda name: True)
        == "ollama run llama3"
    )


# AC-2 corollary: no override falls back to detection via the injected probe.
def test_resolve_falls_back_to_detection() -> None:
    assert resolve_agent_command(None, probe=lambda name: name == "openai") == "openai"


# AC-2 corollary: a blank override is treated as "no override" and detects.
def test_resolve_blank_override_detects() -> None:
    assert resolve_agent_command("  ", probe=lambda name: name == "llm") == "llm"


# AC-2 edge: no override and nothing installed yields None.
def test_resolve_none_when_nothing_detected() -> None:
    assert resolve_agent_command(None, probe=lambda name: False) is None


# AC-3: --stdin mode reads the payload directly from the provided stream.
def test_read_payload_from_stdin() -> None:
    stream = io.StringIO("piped content")
    assert read_payload(True, stream=stream) == "piped content"


# AC-3 corollary: without --stdin the caller-supplied payload is used as-is.
def test_read_payload_uses_supplied_payload() -> None:
    stream = io.StringIO("should be ignored")
    assert read_payload(False, "built payload", stream=stream) == "built payload"


# AC-3 guard: no --stdin and no payload leaves nothing to pipe.
def test_read_payload_requires_payload_without_stdin() -> None:
    with pytest.raises(ValueError):
        read_payload(False)
