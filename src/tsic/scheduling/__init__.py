"""Scheduling layer for tsic.

Hosts the cron-configuration generator (:mod:`tsic.scheduling.cron`, Story 7.1)
that builds and removes the marker-wrapped crontab block used to run
``tsic fetch --all --quiet`` automatically on every trading day.
"""

from tsic.scheduling.cron import (
    DEFAULT_SCHEDULE,
    FETCH_COMMAND,
    MARKER_BEGIN,
    MARKER_END,
    disable,
    enable,
    render_block,
)

__all__ = [
    "DEFAULT_SCHEDULE",
    "FETCH_COMMAND",
    "MARKER_BEGIN",
    "MARKER_END",
    "disable",
    "enable",
    "render_block",
]
