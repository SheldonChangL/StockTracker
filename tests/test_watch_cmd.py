"""Tests for the ``tsic watch add/remove/list`` command group (Story 6.2,
FR-22, AC-1..AC-3)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tsic.commandline.app import app
from tsic.commandline.watch_cmd import _EMPTY_NOTICE

runner = CliRunner()


# AC-1: add then list exits 0 and the list output contains the symbol.
def test_add_then_list_contains_symbol(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"

    add = runner.invoke(app, ["watch", "add", "2330", "--db", str(db_path)])
    assert add.exit_code == 0

    listed = runner.invoke(app, ["watch", "list", "--db", str(db_path)])
    assert listed.exit_code == 0
    assert "2330" in listed.stdout


# AC-2: removing a tracked symbol drops it from the list.
def test_remove_drops_symbol(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    runner.invoke(app, ["watch", "add", "2330", "--db", str(db_path)])

    removed = runner.invoke(app, ["watch", "remove", "2330", "--db", str(db_path)])
    assert removed.exit_code == 0

    listed = runner.invoke(app, ["watch", "list", "--db", str(db_path)])
    assert listed.exit_code == 0
    assert "2330" not in listed.stdout


# AC-3: an empty watchlist prints a friendly notice, exits 0, no error.
def test_empty_list_prints_notice_and_exits_zero(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"

    listed = runner.invoke(app, ["watch", "list", "--db", str(db_path)])

    assert listed.exit_code == 0
    assert listed.exception is None
    assert _EMPTY_NOTICE in listed.stdout


def test_add_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    runner.invoke(app, ["watch", "add", "2330", "--db", str(db_path)])
    runner.invoke(app, ["watch", "add", "2330", "--db", str(db_path)])

    listed = runner.invoke(app, ["watch", "list", "--db", str(db_path)])
    assert listed.exit_code == 0
    assert listed.stdout.count("2330") == 1


def test_remove_untracked_symbol_is_a_noop(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    runner.invoke(app, ["watch", "add", "2330", "--db", str(db_path)])

    removed = runner.invoke(app, ["watch", "remove", "9999", "--db", str(db_path)])
    assert removed.exit_code == 0

    listed = runner.invoke(app, ["watch", "list", "--db", str(db_path)])
    assert "2330" in listed.stdout


def test_list_shows_multiple_symbols_oldest_first(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    runner.invoke(app, ["watch", "add", "2330", "--db", str(db_path)])
    runner.invoke(app, ["watch", "add", "2317", "--db", str(db_path)])

    listed = runner.invoke(app, ["watch", "list", "--db", str(db_path)])
    assert listed.exit_code == 0
    out = listed.stdout
    assert "2330" in out
    assert "2317" in out
    assert out.index("2330") < out.index("2317")
