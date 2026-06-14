"""Tests for the Typer root command tree (Story 1.4)."""

from typer.testing import CliRunner

from tsic.commandline.app import app

runner = CliRunner()

SUBCOMMANDS = ["fetch", "query", "analyze", "db", "watch", "schedule", "tui"]


def test_root_help_lists_all_subcommands() -> None:
    """AC-1: root --help exits 0 and lists every subcommand."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in SUBCOMMANDS:
        assert name in result.stdout


def test_fetch_help() -> None:
    """AC-2: fetch --help shows usage and exits 0."""
    result = runner.invoke(app, ["fetch", "--help"])
    assert result.exit_code == 0
    assert "fetch" in result.stdout
    assert "Usage" in result.stdout


def test_no_subcommand_shows_help_not_traceback() -> None:
    """AC-3: no subcommand prints guidance, not a traceback.

    Typer's ``no_args_is_help`` shows the help screen and exits with the
    conventional "no command" code (2); AC-3 only requires guidance instead of
    a traceback, not a zero exit code.
    """
    result = runner.invoke(app, [])
    assert result.exit_code == 2
    assert "Usage" in result.stdout
    assert "Traceback" not in result.stdout
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_global_flags_visible_in_help() -> None:
    """AC-4: --quiet and --verbose appear in root help."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--quiet" in result.stdout
    assert "--verbose" in result.stdout


def test_quiet_suppresses_stub_output() -> None:
    """--quiet suppresses the stub notice for a not-yet-implemented subcommand."""
    result = runner.invoke(app, ["--quiet", "tui"])
    assert result.exit_code == 0
    assert result.stdout.strip() == ""
