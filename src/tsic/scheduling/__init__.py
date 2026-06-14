"""Scheduling layer for tsic.

Hosts the platform-specific schedulers that run ``tsic fetch --all --quiet``
automatically on every trading day:

* :mod:`tsic.scheduling.cron` (Story 7.1) — builds and removes the
  marker-wrapped crontab block used on Linux.
* :mod:`tsic.scheduling.launchd` (Story 7.2) — writes and removes the macOS
  LaunchAgent plist.

The cron helpers are re-exported here for convenience; launchd is exposed as a
submodule (``from tsic.scheduling import launchd``) to avoid colliding with
cron's ``enable``/``disable`` names.
"""

from tsic.scheduling import launchd
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
    "launchd",
    "render_block",
]
