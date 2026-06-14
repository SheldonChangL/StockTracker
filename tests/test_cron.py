"""Tests for the cron-configuration generator (Story 7.1, FR-23, OPS-4).

Every test injects a fake crontab *string* and asserts on the returned string —
no real ``crontab`` is touched (AC-4).
"""

from __future__ import annotations

from tsic.scheduling import cron

# A user's pre-existing, unrelated crontab to prove we never disturb it (AC-3).
OTHER_ENTRIES = "# my backup\n0 2 * * * /usr/bin/backup.sh\n"


# AC-1: default schedule and command when no --cron is given.
def test_enable_uses_default_schedule_and_command() -> None:
    result = cron.enable("")

    assert "0 18 * * 1-5 tsic fetch --all --quiet" in result
    assert cron.MARKER_BEGIN in result
    assert cron.MARKER_END in result


# AC-2: a custom schedule string is used verbatim.
def test_enable_uses_custom_schedule() -> None:
    result = cron.enable("", schedule="30 17 * * 1-5")

    assert "30 17 * * 1-5 tsic fetch --all --quiet" in result
    assert "0 18 * * 1-5" not in result


# AC-1 corollary: a blank/whitespace --cron falls back to the default.
def test_blank_schedule_falls_back_to_default() -> None:
    assert "0 18 * * 1-5" in cron.enable("", schedule="   ")


# AC-3: disabling removes the tsic block entirely, with no residue.
def test_disable_removes_tsic_block_completely() -> None:
    enabled = cron.enable("")
    disabled = cron.disable(enabled)

    assert cron.MARKER_BEGIN not in disabled
    assert cron.MARKER_END not in disabled
    assert "tsic fetch" not in disabled
    assert disabled == ""


# AC-3: other users' entries survive enable + disable untouched.
def test_other_entries_are_preserved_across_enable_and_disable() -> None:
    enabled = cron.enable(OTHER_ENTRIES)
    assert OTHER_ENTRIES.strip() in enabled  # the user's lines remain
    assert "tsic fetch --all --quiet" in enabled  # alongside the tsic block

    disabled = cron.disable(enabled)
    assert disabled == OTHER_ENTRIES  # back to exactly the original, no residue


# AC-4: the block is fenced by recognizable markers in the right order.
def test_block_is_wrapped_by_markers() -> None:
    block = cron.render_block()
    lines = block.splitlines()

    assert lines[0] == cron.MARKER_BEGIN
    assert lines[-1] == cron.MARKER_END
    assert lines[1] == "0 18 * * 1-5 tsic fetch --all --quiet"


# Idempotency: enabling twice leaves exactly one tsic block.
def test_enable_is_idempotent() -> None:
    once = cron.enable(OTHER_ENTRIES)
    twice = cron.enable(once)

    assert twice == once
    assert twice.count(cron.MARKER_BEGIN) == 1
    assert twice.count(cron.MARKER_END) == 1


# Re-enabling with a new schedule replaces the entry in place (no stale block).
def test_re_enable_changes_schedule_in_place() -> None:
    enabled = cron.enable("", schedule="0 18 * * 1-5")
    rescheduled = cron.enable(enabled, schedule="30 17 * * 1-5")

    assert "30 17 * * 1-5 tsic fetch --all --quiet" in rescheduled
    assert "0 18 * * 1-5" not in rescheduled
    assert rescheduled.count(cron.MARKER_BEGIN) == 1


# Disabling a crontab with no tsic block leaves the other entries intact.
def test_disable_without_tsic_block_is_a_noop() -> None:
    assert cron.disable(OTHER_ENTRIES) == OTHER_ENTRIES


# Robustness: a stray tsic block in the middle is excised, neighbours kept.
def test_disable_excises_block_between_other_entries() -> None:
    crontab = (
        "0 1 * * * /first.sh\n"
        f"{cron.MARKER_BEGIN}\n"
        "0 18 * * 1-5 tsic fetch --all --quiet\n"
        f"{cron.MARKER_END}\n"
        "0 3 * * * /last.sh\n"
    )

    disabled = cron.disable(crontab)

    assert disabled == "0 1 * * * /first.sh\n0 3 * * * /last.sh\n"
