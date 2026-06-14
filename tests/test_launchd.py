"""Tests for the macOS launchd plist generator (Story 7.2, FR-23, OPS-4).

Every test that writes a plist injects a temporary directory (``tmp_path``) so
no test ever touches the real ``~/Library/LaunchAgents`` (AC-3).
"""

from __future__ import annotations

import plistlib
from pathlib import Path

from tsic.scheduling import launchd


# AC-1: the rendered plist carries Label, the fetch argv, and a Mon-Fri 18:00
# StartCalendarInterval.
def test_render_plist_has_required_fields() -> None:
    parsed = plistlib.loads(launchd.render_plist().encode("utf-8"))

    assert parsed["Label"] == launchd.LABEL
    assert parsed["ProgramArguments"] == ["tsic", "fetch", "--all", "--quiet"]

    intervals = parsed["StartCalendarInterval"]
    assert [entry["Weekday"] for entry in intervals] == [1, 2, 3, 4, 5]
    assert all(entry["Hour"] == 18 for entry in intervals)
    assert all(entry["Minute"] == 0 for entry in intervals)


# AC-1: a custom schedule is honoured verbatim.
def test_render_plist_honours_custom_schedule() -> None:
    parsed = plistlib.loads(
        launchd.render_plist(hour=17, minute=30, weekdays=(1, 3, 5)).encode("utf-8")
    )

    intervals = parsed["StartCalendarInterval"]
    assert [entry["Weekday"] for entry in intervals] == [1, 3, 5]
    assert all(entry["Hour"] == 17 and entry["Minute"] == 30 for entry in intervals)


# AC-1: enable writes a parseable plist into the injected directory.
def test_enable_writes_plist_into_injected_directory(tmp_path: Path) -> None:
    path = launchd.enable(tmp_path)

    assert path == tmp_path / f"{launchd.LABEL}.plist"
    assert path.exists()

    parsed = plistlib.loads(path.read_bytes())
    assert parsed["Label"] == launchd.LABEL
    assert parsed["ProgramArguments"] == ["tsic", "fetch", "--all", "--quiet"]


# AC-1: enable creates the target directory if it does not yet exist.
def test_enable_creates_missing_directory(tmp_path: Path) -> None:
    target = tmp_path / "LaunchAgents"
    assert not target.exists()

    path = launchd.enable(target)

    assert path.exists()
    assert path.parent == target


# AC-2: disable removes the plist file with no residue.
def test_disable_removes_plist(tmp_path: Path) -> None:
    launchd.enable(tmp_path)

    removed = launchd.disable(tmp_path)

    assert removed is True
    assert not (tmp_path / f"{launchd.LABEL}.plist").exists()
    assert list(tmp_path.iterdir()) == []


# AC-2: disabling when nothing is installed is a safe no-op (idempotent).
def test_disable_without_plist_is_noop(tmp_path: Path) -> None:
    assert launchd.disable(tmp_path) is False


# AC-1 corollary: enabling twice leaves exactly one plist with the latest schedule.
def test_enable_is_idempotent(tmp_path: Path) -> None:
    launchd.enable(tmp_path)
    launchd.enable(tmp_path, hour=17, minute=30)

    plists = list(tmp_path.glob("*.plist"))
    assert len(plists) == 1

    parsed = plistlib.loads(plists[0].read_bytes())
    assert parsed["StartCalendarInterval"][0]["Hour"] == 17
    assert parsed["StartCalendarInterval"][0]["Minute"] == 30


# AC-3: a custom label drives both the filename and the plist Label field.
def test_custom_label_drives_filename(tmp_path: Path) -> None:
    path = launchd.enable(tmp_path, label="com.example.test")

    assert path.name == "com.example.test.plist"
    parsed = plistlib.loads(path.read_bytes())
    assert parsed["Label"] == "com.example.test"

    assert launchd.disable(tmp_path, label="com.example.test") is True
    assert not path.exists()
