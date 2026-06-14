"""Generate and remove the tsic-managed launchd plist (Story 7.2, FR-23, OPS-4).

On macOS, the cron approach used on Linux (:mod:`tsic.scheduling.cron`) is not
the idiomatic scheduler — launchd is. This module is the macOS counterpart: it
materialises a single *LaunchAgent* property-list file that asks launchd to run
``tsic fetch --all --quiet`` on every trading day, and removes that file cleanly
when scheduling is disabled.

Unlike the cron generator — whose core is a pure string transform — launchd is
inherently file-based: a LaunchAgent only exists as a ``.plist`` file in a
well-known directory (normally ``~/Library/LaunchAgents``). So this module *does*
touch the filesystem, but the target directory is always **injected** by the
caller. The CLI passes the real ``~/Library/LaunchAgents``; tests pass a
temporary directory, so no test ever writes to the user's real LaunchAgents
folder (AC-3).

* :func:`render_plist` — build the plist XML for the schedule (AC-1), no I/O.
* :func:`enable`       — write the plist into the given directory, return its
  path (AC-1).
* :func:`disable`      — remove the plist from the given directory, leaving no
  residue; idempotent (AC-2).
"""

from __future__ import annotations

import plistlib
from pathlib import Path

#: launchd job identifier; also the plist filename stem (``<LABEL>.plist``).
LABEL = "com.tsic.fetch"

#: Argument vector launchd executes: refresh every tracked symbol, quietly (AC-1).
#: launchd does not run a shell, so the command is an explicit argv, not a string.
PROGRAM_ARGUMENTS = ["tsic", "fetch", "--all", "--quiet"]

#: Default run time: 18:00, i.e. after the Taiwan trading day closes (AC-1).
DEFAULT_HOUR = 18
DEFAULT_MINUTE = 0

#: Trading days as launchd weekday numbers (1=Mon ... 5=Fri); Mon-Fri (AC-1).
TRADING_WEEKDAYS = (1, 2, 3, 4, 5)


def _calendar_intervals(
    hour: int, minute: int, weekdays: tuple[int, ...]
) -> list[dict[str, int]]:
    """Build the ``StartCalendarInterval`` array: one entry per trading day.

    launchd fires the job whenever the wall clock matches any entry, so a
    weekday-restricted daily schedule is expressed as one ``{Weekday, Hour,
    Minute}`` dict per weekday (AC-1).
    """
    return [
        {"Weekday": day, "Hour": hour, "Minute": minute} for day in weekdays
    ]


def render_plist(
    *,
    label: str = LABEL,
    program_arguments: list[str] | None = None,
    hour: int = DEFAULT_HOUR,
    minute: int = DEFAULT_MINUTE,
    weekdays: tuple[int, ...] = TRADING_WEEKDAYS,
) -> str:
    """Render the LaunchAgent plist XML for the given schedule (AC-1).

    The plist carries the three fields launchd needs to run the fetch job on a
    weekday schedule:

    * ``Label`` — the job identifier (also the filename stem).
    * ``ProgramArguments`` — the argv launchd executes (``tsic fetch --all
      --quiet`` by default).
    * ``StartCalendarInterval`` — one entry per trading day at ``hour:minute``.

    Args:
        label: launchd job label; defaults to :data:`LABEL`.
        program_arguments: argv to run; defaults to :data:`PROGRAM_ARGUMENTS`.
        hour: hour of day (0-23) to run; defaults to :data:`DEFAULT_HOUR`.
        minute: minute of hour (0-59) to run; defaults to :data:`DEFAULT_MINUTE`.
        weekdays: launchd weekday numbers to run on; defaults to
            :data:`TRADING_WEEKDAYS` (Mon-Fri).

    Returns:
        The plist as an XML string.
    """
    payload = {
        "Label": label,
        "ProgramArguments": list(program_arguments or PROGRAM_ARGUMENTS),
        "StartCalendarInterval": _calendar_intervals(hour, minute, weekdays),
    }
    return plistlib.dumps(payload).decode("utf-8")


def plist_path(directory: Path | str, *, label: str = LABEL) -> Path:
    """Return the plist file path for ``label`` inside ``directory``.

    The directory is injected by the caller (real ``~/Library/LaunchAgents`` in
    production, a temp dir in tests, AC-3); the filename is ``<label>.plist``.
    """
    return Path(directory) / f"{label}.plist"


def enable(
    directory: Path | str,
    *,
    label: str = LABEL,
    program_arguments: list[str] | None = None,
    hour: int = DEFAULT_HOUR,
    minute: int = DEFAULT_MINUTE,
    weekdays: tuple[int, ...] = TRADING_WEEKDAYS,
) -> Path:
    """Write the LaunchAgent plist into ``directory`` and return its path (AC-1).

    The target directory is created if missing (``mkdir -p`` semantics) so the
    caller need not pre-create ``~/Library/LaunchAgents``. Writing is a plain
    overwrite, which makes the operation idempotent — enabling twice leaves
    exactly one plist with the latest schedule.

    Args:
        directory: directory to write the plist into (injected by the caller).
        label: launchd job label / filename stem; defaults to :data:`LABEL`.
        program_arguments: argv to run; defaults to :data:`PROGRAM_ARGUMENTS`.
        hour: hour of day to run; defaults to :data:`DEFAULT_HOUR`.
        minute: minute of hour to run; defaults to :data:`DEFAULT_MINUTE`.
        weekdays: weekday numbers to run on; defaults to :data:`TRADING_WEEKDAYS`.

    Returns:
        The path of the written plist file.
    """
    path = plist_path(directory, label=label)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_plist(
            label=label,
            program_arguments=program_arguments,
            hour=hour,
            minute=minute,
            weekdays=weekdays,
        ),
        encoding="utf-8",
    )
    return path


def disable(directory: Path | str, *, label: str = LABEL) -> bool:
    """Remove the LaunchAgent plist from ``directory``, leaving no residue (AC-2).

    Idempotent: removing a plist that is not present is a no-op rather than an
    error, so a disable after a disable (or with scheduling never enabled) is
    safe.

    Args:
        directory: directory to remove the plist from (injected by the caller).
        label: launchd job label / filename stem; defaults to :data:`LABEL`.

    Returns:
        ``True`` if a plist file was removed, ``False`` if none existed.
    """
    path = plist_path(directory, label=label)
    if path.exists():
        path.unlink()
        return True
    return False
