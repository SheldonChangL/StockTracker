"""AI integration layer: detect and drive an installed AI CLI for tsic."""

from __future__ import annotations

from tsic.ai.detector import CLI_PRIORITY, detect
from tsic.ai.formatter import DEFAULT_PROMPT_TEMPLATE, build_prompt, to_markdown

__all__ = [
    "CLI_PRIORITY",
    "DEFAULT_PROMPT_TEMPLATE",
    "build_prompt",
    "detect",
    "to_markdown",
]
