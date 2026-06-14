"""Generate and remove the tsic-managed crontab block (Story 7.1, FR-23, OPS-4).

On Linux, automatic end-of-trading-day updates are wired through ``cron``: tsic
appends a single, marker-wrapped block to the user's crontab that runs
``tsic fetch --all --quiet`` on every trading day. The two markers
(:data:`MARKER_BEGIN` / :data:`MARKER_END`) fence that block so it can later be
removed *precisely*, without disturbing any other entry the user maintains.

This module is the pure, side-effect-free core of that workflow: every function
takes the current crontab *as a string* and returns the new crontab *as a
string*. It never shells out to ``crontab`` itself, which keeps it trivially
testable by injecting a fake crontab string (AC-4) and leaves the choice of how
to read/write the real crontab to the calling CLI command.

* :func:`enable`  — add (or refresh) the tsic block, leaving everything else
  untouched (AC-1, AC-2).
* :func:`disable` — remove the tsic block completely, with no residue, and no
  effect on the user's other entries (AC-3).
"""

from __future__ import annotations

#: Opening fence of the tsic-managed block; unique enough to match precisely.
MARKER_BEGIN = "# >>> tsic schedule (managed) >>>"

#: Closing fence of the tsic-managed block.
MARKER_END = "# <<< tsic schedule (managed) <<<"

#: Default schedule: 18:00 on weekdays (Mon-Fri), i.e. every trading day (AC-1).
DEFAULT_SCHEDULE = "0 18 * * 1-5"

#: Command the scheduled job runs: refresh every tracked symbol, quietly (AC-1).
FETCH_COMMAND = "tsic fetch --all --quiet"


def render_block(schedule: str | None = None) -> str:
    """Render the marker-wrapped cron block for the given ``schedule``.

    The block is exactly three lines — opening marker, the cron entry, closing
    marker — and carries no trailing newline so callers control spacing.

    Args:
        schedule: A cron schedule expression. When ``None`` or blank, the
            default weekday-18:00 schedule (:data:`DEFAULT_SCHEDULE`) is used
            (AC-1); any other value is used verbatim (AC-2).

    Returns:
        The marker-fenced cron block as a string.
    """
    expr = schedule.strip() if schedule and schedule.strip() else DEFAULT_SCHEDULE
    return f"{MARKER_BEGIN}\n{expr} {FETCH_COMMAND}\n{MARKER_END}"


def _strip_block(crontab: str) -> str:
    """Return ``crontab`` with every tsic-managed block removed.

    Lines from :data:`MARKER_BEGIN` through :data:`MARKER_END` (inclusive) are
    dropped. All other lines are preserved in order, so a user's unrelated
    entries are never touched (AC-3). Robust against an unterminated or repeated
    block: any line between an opening marker and the next closing marker (or
    end of input) is removed.
    """
    kept: list[str] = []
    inside = False
    for line in crontab.splitlines():
        stripped = line.strip()
        if not inside and stripped == MARKER_BEGIN:
            inside = True
            continue
        if inside:
            if stripped == MARKER_END:
                inside = False
            continue
        kept.append(line)
    return "\n".join(kept)


def disable(crontab: str) -> str:
    """Remove the tsic-managed block from ``crontab``, leaving no residue (AC-3).

    Other entries are preserved exactly; only the marker-fenced tsic block is
    dropped. Trailing blank lines left behind by the removal are trimmed, and a
    non-empty result ends with a single newline (the conventional crontab shape).
    Disabling a crontab that has no tsic block returns it unchanged (modulo that
    trailing-newline normalisation), so the operation is idempotent.

    Args:
        crontab: The current crontab contents.

    Returns:
        The crontab with the tsic block removed.
    """
    return _normalise(_strip_block(crontab))


def enable(crontab: str, schedule: str | None = None) -> str:
    """Add (or refresh) the tsic-managed block in ``crontab`` (AC-1, AC-2).

    Any pre-existing tsic block is removed first, then a fresh block for
    ``schedule`` is appended. This makes the operation idempotent — enabling
    twice leaves exactly one block — and lets a repeated call change the
    schedule in place without leaving a stale entry behind.

    Args:
        crontab: The current crontab contents.
        schedule: The cron schedule expression; ``None`` selects the default
            (:data:`DEFAULT_SCHEDULE`).

    Returns:
        The crontab with exactly one tsic block appended.
    """
    base = _strip_block(crontab).strip("\n")
    block = render_block(schedule)
    body = f"{base}\n{block}" if base else block
    return _normalise(body)


def _normalise(text: str) -> str:
    """Trim surrounding blank lines; end a non-empty result with one newline."""
    trimmed = text.strip("\n")
    return f"{trimmed}\n" if trimmed else ""
