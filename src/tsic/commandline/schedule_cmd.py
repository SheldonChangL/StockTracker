"""The ``tsic schedule`` command group: enable/disable automatic updates
(Story 7.3, FR-23, OPS-4).

This is the *vertical* CLI entry point over the platform-specific schedulers
delivered by Stories 7.1/7.2:

* On **Linux** the job is wired through ``cron``. :mod:`tsic.scheduling.cron`
  is a pure string transform, so this command owns the I/O: it reads the
  current crontab (``crontab -l``), applies :func:`cron.enable` /
  :func:`cron.disable`, and writes it back (``crontab -``).
* On **macOS** the job is a launchd LaunchAgent. :mod:`tsic.scheduling.launchd`
  already does the file I/O; this command just selects the target directory
  (``~/Library/LaunchAgents``) and delegates.

Both the **platform** and the **target location** are injectable so the command
is exercised end-to-end in tests without touching the real crontab or the user's
``~/Library/LaunchAgents`` (the defining trait of this vertical):

* ``--system``        — override :func:`platform.system` (force Linux/Darwin).
* ``--launchd-dir``   — override the LaunchAgents directory (macOS path).
* ``--crontab-file``  — read/write a file instead of shelling out to ``crontab``
  (Linux path); production leaves this unset and uses the real crontab.

These three options are hidden: they exist for testing and advanced use, not the
everyday ``tsic schedule enable`` / ``tsic schedule disable`` flow.
"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

import typer

from tsic.scheduling import cron, launchd

#: ``platform.system()`` value for Linux (cron path, AC-1).
_LINUX = "Linux"

#: ``platform.system()`` value for macOS (launchd path, AC-2).
_MACOS = "Darwin"

#: Hidden seam: force the platform instead of detecting it (AC-1 injection).
_SYSTEM_OPTION = typer.Option(
    None,
    "--system",
    hidden=True,
    help="覆寫平台判斷（測試/進階用，例如 Linux 或 Darwin）。",
)

#: Hidden seam: override the LaunchAgents directory (macOS path, AC-2/AC-3).
_LAUNCHD_DIR_OPTION = typer.Option(
    None,
    "--launchd-dir",
    hidden=True,
    help="覆寫 launchd LaunchAgents 目錄（預設 ~/Library/LaunchAgents）。",
)

#: Hidden seam: read/write a crontab file instead of the real ``crontab`` (Linux).
_CRONTAB_FILE_OPTION = typer.Option(
    None,
    "--crontab-file",
    hidden=True,
    help="改以檔案讀寫取代真實 crontab（測試/進階用）。",
)

#: ``--cron`` custom schedule expression for the cron path (AC-4).
_CRON_OPTION = typer.Option(
    None,
    "--cron",
    help='自訂 cron 排程（例如 "0 19 * * 1-5"）；未指定時用預設排程。',
)

schedule_app = typer.Typer(
    name="schedule",
    help="啟用或停用自動更新排程（Linux 走 cron、macOS 走 launchd）。",
    no_args_is_help=True,
    add_completion=False,
)


def _default_launch_agents_dir() -> Path:
    """Return the user's LaunchAgents directory (``~/Library/LaunchAgents``)."""
    return Path.home() / "Library" / "LaunchAgents"


def _resolve_system(override: str | None) -> str:
    """Return the effective platform name: the override if given, else detected."""
    return override or platform.system()


def _read_crontab(crontab_file: Path | None) -> str:
    """Read the current crontab from ``crontab_file`` or the real ``crontab``.

    An absent file (or a user with no crontab, where ``crontab -l`` exits
    non-zero) is treated as an empty crontab, so enabling for the first time
    works cleanly.
    """
    if crontab_file is not None:
        return crontab_file.read_text(encoding="utf-8") if crontab_file.exists() else ""
    result = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True, check=False
    )
    return result.stdout if result.returncode == 0 else ""


def _write_crontab(crontab_file: Path | None, text: str) -> None:
    """Write ``text`` back to ``crontab_file`` or install it via ``crontab -``."""
    if crontab_file is not None:
        crontab_file.write_text(text, encoding="utf-8")
        return
    subprocess.run(["crontab", "-"], input=text, text=True, check=True)


def _unsupported(system: str) -> None:
    """Report an unsupported platform and exit non-zero."""
    typer.echo(f"未支援的平台：{system}（僅支援 Linux 與 macOS）。", err=True)
    raise typer.Exit(code=1)


@schedule_app.command()
def enable(
    cron_expr: str | None = _CRON_OPTION,
    system: str | None = _SYSTEM_OPTION,
    launchd_dir: Path | None = _LAUNCHD_DIR_OPTION,
    crontab_file: Path | None = _CRONTAB_FILE_OPTION,
) -> None:
    """Enable automatic end-of-trading-day updates for the current platform."""
    resolved = _resolve_system(system)

    if resolved == _MACOS:
        directory = launchd_dir or _default_launch_agents_dir()
        path = launchd.enable(directory)
        typer.echo(f"已啟用自動更新排程（launchd）：{path}")
        return

    if resolved == _LINUX:
        current = _read_crontab(crontab_file)
        _write_crontab(crontab_file, cron.enable(current, schedule=cron_expr))
        expr = (
            cron_expr.strip()
            if cron_expr and cron_expr.strip()
            else cron.DEFAULT_SCHEDULE
        )
        typer.echo(f"已啟用自動更新排程（cron）：{expr}")
        return

    _unsupported(resolved)


@schedule_app.command()
def disable(
    system: str | None = _SYSTEM_OPTION,
    launchd_dir: Path | None = _LAUNCHD_DIR_OPTION,
    crontab_file: Path | None = _CRONTAB_FILE_OPTION,
) -> None:
    """Disable automatic updates, removing the platform-specific schedule."""
    resolved = _resolve_system(system)

    if resolved == _MACOS:
        directory = launchd_dir or _default_launch_agents_dir()
        launchd.disable(directory)
        typer.echo("已停用自動更新排程（launchd）。")
        return

    if resolved == _LINUX:
        current = _read_crontab(crontab_file)
        _write_crontab(crontab_file, cron.disable(current))
        typer.echo("已停用自動更新排程（cron）。")
        return

    _unsupported(resolved)
