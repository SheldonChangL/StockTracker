"""AI integration layer: detect and drive an installed AI CLI for tsic."""

from __future__ import annotations

from tsic.ai.detector import CLI_PRIORITY, detect

__all__ = [
    "CLI_PRIORITY",
    "detect",
]
