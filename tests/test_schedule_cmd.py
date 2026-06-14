"""Tests for the ``tsic schedule`` CLI command (Story 7.3, FR-23, OPS-4).

The platform and the target location are injected via hidden options
(``--system``, ``--launchd-dir``, ``--crontab-file``) so the real CLI is driven
end-to-end without ever touching the user's crontab or ~/Library/LaunchAgents.
"""

from __future__ import annotations

import plistlib

from typer.testing import CliRunner

from tsic.commandline.app import app
from tsic.scheduling import cron, launchd

runner = CliRunner()


# AC-1: Linux enable writes the default cron schedule, exits 0, confirms.
def test_enable_linux_writes_default_cron(tmp_path) -> None:
    crontab = tmp_path / "crontab.txt"

    result = runner.invoke(
        app,
        ["schedule", "enable", "--system", "Linux", "--crontab-file", str(crontab)],
    )

    assert result.exit_code == 0
    assert "已啟用" in result.stdout
    written = crontab.read_text(encoding="utf-8")
    assert cron.MARKER_BEGIN in written
    assert cron.MARKER_END in written
    assert f"{cron.DEFAULT_SCHEDULE} {cron.FETCH_COMMAND}" in written


# AC-1: an existing, unrelated crontab is preserved when enabling.
def test_enable_linux_preserves_existing_entries(tmp_path) -> None:
    crontab = tmp_path / "crontab.txt"
    crontab.write_text("0 9 * * * echo hello\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["schedule", "enable", "--system", "Linux", "--crontab-file", str(crontab)],
    )

    assert result.exit_code == 0
    written = crontab.read_text(encoding="utf-8")
    assert "0 9 * * * echo hello" in written
    assert written.count(cron.MARKER_BEGIN) == 1


# AC-2: macOS enable writes a launchd plist into the injected directory.
def test_enable_macos_writes_launchd_plist(tmp_path) -> None:
    result = runner.invoke(
        app,
        ["schedule", "enable", "--system", "Darwin", "--launchd-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "launchd" in result.stdout
    plist = tmp_path / f"{launchd.LABEL}.plist"
    assert plist.exists()
    parsed = plistlib.loads(plist.read_bytes())
    assert parsed["Label"] == launchd.LABEL


# AC-3: Linux disable removes the tsic block, exits 0.
def test_disable_linux_removes_cron_block(tmp_path) -> None:
    crontab = tmp_path / "crontab.txt"
    runner.invoke(
        app,
        ["schedule", "enable", "--system", "Linux", "--crontab-file", str(crontab)],
    )

    result = runner.invoke(
        app,
        ["schedule", "disable", "--system", "Linux", "--crontab-file", str(crontab)],
    )

    assert result.exit_code == 0
    written = crontab.read_text(encoding="utf-8")
    assert cron.MARKER_BEGIN not in written
    assert cron.MARKER_END not in written


# AC-3: macOS disable removes the plist, exits 0.
def test_disable_macos_removes_launchd_plist(tmp_path) -> None:
    runner.invoke(
        app,
        ["schedule", "enable", "--system", "Darwin", "--launchd-dir", str(tmp_path)],
    )

    result = runner.invoke(
        app,
        ["schedule", "disable", "--system", "Darwin", "--launchd-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert not (tmp_path / f"{launchd.LABEL}.plist").exists()


# AC-4: a custom --cron schedule is honoured verbatim on the cron path.
def test_enable_linux_honours_custom_cron(tmp_path) -> None:
    crontab = tmp_path / "crontab.txt"

    result = runner.invoke(
        app,
        [
            "schedule",
            "enable",
            "--system",
            "Linux",
            "--crontab-file",
            str(crontab),
            "--cron",
            "0 19 * * 1-5",
        ],
    )

    assert result.exit_code == 0
    assert "0 19 * * 1-5" in result.stdout
    written = crontab.read_text(encoding="utf-8")
    assert f"0 19 * * 1-5 {cron.FETCH_COMMAND}" in written
    assert cron.DEFAULT_SCHEDULE not in written


# An unsupported platform fails cleanly with exit code 1.
def test_enable_unsupported_platform_exits_nonzero(tmp_path) -> None:
    result = runner.invoke(app, ["schedule", "enable", "--system", "Windows"])

    assert result.exit_code == 1


# No subcommand shows guidance (Typer no_args_is_help), not a traceback.
def test_schedule_no_subcommand_shows_help() -> None:
    result = runner.invoke(app, ["schedule"])

    assert result.exit_code == 2
    assert "Usage" in result.stdout
