"""Textual terminal-UI package for tsic (Story 8.x, FR-26/FR-27).

The TUI is the interactive front end over the same storage layer the CLI uses.
This story (8.1) lays the foundation: a :class:`~tsic.tui.app.TsicApp` whose main
screen lists the watchlist and each symbol's data freshness in a table with a
stable ``id`` for test automation.
"""

from __future__ import annotations

from tsic.tui.app import TsicApp

__all__ = ["TsicApp"]
