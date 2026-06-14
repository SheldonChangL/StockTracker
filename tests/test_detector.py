"""Tests for the AI CLI detector (Story 5.1, AC-1..AC-4)."""

from __future__ import annotations

from collections.abc import Callable

from tsic.ai.detector import CLI_PRIORITY, detect


def _probe_for(*available: str) -> Callable[[str], bool]:
    """Build an injectable PATH probe that reports ``available`` names (AC-4)."""
    present = set(available)
    return lambda name: name in present


# AC-1: claude and openai both present -> the higher-priority claude wins.
def test_claude_preferred_over_openai() -> None:
    assert detect(_probe_for("claude", "openai")) == "claude"


# AC-1 corollary: full preference order is honoured across all three.
def test_preference_order_is_claude_openai_llm() -> None:
    assert detect(_probe_for("claude", "openai", "llm")) == "claude"
    assert detect(_probe_for("openai", "llm")) == "openai"


# AC-2: only llm present -> llm is detected.
def test_only_llm_returns_llm() -> None:
    assert detect(_probe_for("llm")) == "llm"


# AC-3: none present -> None (command layer maps this to exit code 3).
def test_none_present_returns_none() -> None:
    assert detect(_probe_for()) is None


# AC-3 corollary: an unrelated executable on PATH does not count.
def test_unrelated_cli_is_ignored() -> None:
    assert detect(_probe_for("git", "python")) is None


# AC-4: detection uses the injected probe and never touches the real PATH.
def test_uses_injected_probe_only() -> None:
    probed: list[str] = []

    def recording_probe(name: str) -> bool:
        probed.append(name)
        return name == "openai"

    assert detect(recording_probe) == "openai"
    # Stops at the first hit; claude was checked, llm never reached.
    assert probed == ["claude", "openai"]


def test_priority_constant_order() -> None:
    assert CLI_PRIORITY == ("claude", "openai", "llm")
