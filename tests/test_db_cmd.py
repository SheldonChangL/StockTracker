"""Tests for the ``tsic db clean`` (Story 2.5) and ``db status`` (Story 2.6)
commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tsic import settings
from tsic.commandline.app import app
from tsic.storage import database, maintenance, migrations

runner = CliRunner()


def _make_db(path: Path, symbol: str = "2330", rows: int = 3) -> int:
    """Seed ``rows`` daily-price records for ``symbol`` and return the count."""
    conn = database.connect(path)
    try:
        migrations.migrate(conn)
        for day in range(rows):
            conn.execute(
                "INSERT INTO daily_prices "
                "(symbol, date, open, high, low, close, volume, source, adjusted) "
                "VALUES (?, ?, 1, 1, 1, 1, 1, 'test', 0)",
                (symbol, f"2026-06-{10 + day:02d}"),
            )
        conn.commit()
        return maintenance.count_symbol_records(conn, symbol)
    finally:
        conn.close()


def _count(path: Path, symbol: str) -> int:
    conn = database.connect(path)
    try:
        return maintenance.count_symbol_records(conn, symbol)
    finally:
        conn.close()


# AC-1: answering "n" cancels, deletes nothing, exits 0, prints a cancel notice.
def test_clean_cancel_with_n(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    _make_db(db_path, "2330", rows=3)

    result = runner.invoke(
        app, ["db", "clean", "2330", "--db-path", str(db_path)], input="n\n"
    )

    assert result.exit_code == 0
    assert "已取消" in result.stdout
    assert _count(db_path, "2330") == 3


# AC-1: empty input (just Enter) also cancels (default is N).
def test_clean_cancel_with_enter(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    _make_db(db_path, "2330", rows=3)

    result = runner.invoke(
        app, ["db", "clean", "2330", "--db-path", str(db_path)], input="\n"
    )

    assert result.exit_code == 0
    assert _count(db_path, "2330") == 3


# AC-2: answering "y" deletes all of the symbol's rows and exits 0.
def test_clean_confirm_with_y_deletes(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    _make_db(db_path, "2330", rows=3)

    result = runner.invoke(
        app, ["db", "clean", "2330", "--db-path", str(db_path)], input="y\n"
    )

    assert result.exit_code == 0
    assert _count(db_path, "2330") == 0


def test_clean_only_deletes_target_symbol(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    _make_db(db_path, "2330", rows=2)
    _make_db(db_path, "2454", rows=2)

    result = runner.invoke(
        app, ["db", "clean", "2330", "--db-path", str(db_path)], input="y\n"
    )

    assert result.exit_code == 0
    assert _count(db_path, "2330") == 0
    assert _count(db_path, "2454") == 2


# AC-3: confirmation prompt shows the exact text with default N.
def test_clean_prompt_text(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    count = _make_db(db_path, "2330", rows=3)

    result = runner.invoke(
        app, ["db", "clean", "2330", "--db-path", str(db_path)], input="n\n"
    )

    assert f"將刪除 2330 共 {count} 筆記錄，確認？(y/N)" in result.stdout


def test_clean_zero_records_prompts_with_zero(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    database.connect(db_path).close()  # create + migrate-on-clean, no data

    result = runner.invoke(
        app, ["db", "clean", "2330", "--db-path", str(db_path)], input="y\n"
    )

    assert result.exit_code == 0
    assert "將刪除 2330 共 0 筆記錄" in result.stdout


# --- db status (Story 2.6) ---------------------------------------------------


# AC-1: a missing default ~/.tsic/ is auto-created, reports 0 tracked, exits 0.
def test_status_missing_default_db_auto_creates_and_reports_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default_db = tmp_path / ".tsic" / "data.db"
    monkeypatch.setattr(settings, "default_db_path", lambda: default_db)
    assert not default_db.parent.exists()

    result = runner.invoke(app, ["db", "status"])

    assert result.exit_code == 0
    assert "0 檔追蹤" in result.stdout
    assert default_db.exists()  # real connect/migrate created it


# AC-2: a populated db shows file size, tracked count, and per-symbol dates.
def test_status_reports_size_count_and_latest_dates(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    _make_db(db_path, "2330", rows=2)  # 2026-06-10, 2026-06-11
    _make_db(db_path, "2317", rows=3)  # 2026-06-10, 2026-06-11, 2026-06-12

    result = runner.invoke(app, ["db", "status", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "追蹤股票數：2" in result.stdout
    assert f"{db_path.stat().st_size} bytes" in result.stdout
    assert "2330  最新資料日期：2026-06-11" in result.stdout
    assert "2317  最新資料日期：2026-06-12" in result.stdout


def test_status_counts_symbols_across_all_data_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    conn = database.connect(db_path)
    try:
        migrations.migrate(conn)
        conn.execute(
            "INSERT INTO chip_flows "
            "(symbol, date, foreign_net, trust_net, dealer_net, source) "
            "VALUES ('2603', '2026-06-09', 0, 0, 0, 'test')"
        )
        conn.commit()
    finally:
        conn.close()

    result = runner.invoke(app, ["db", "status", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "追蹤股票數：1" in result.stdout
    assert "2603  最新資料日期：2026-06-09" in result.stdout


# AC-3: --db targets the given path, not the default.
def test_status_db_option_targets_custom_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default_db = tmp_path / "default" / "data.db"
    monkeypatch.setattr(settings, "default_db_path", lambda: default_db)
    custom_db = tmp_path / "custom" / "x.db"
    _make_db(custom_db, "2330", rows=1)

    result = runner.invoke(app, ["db", "status", "--db", str(custom_db)])

    assert result.exit_code == 0
    assert str(custom_db) in result.stdout
    assert "追蹤股票數：1" in result.stdout
    assert not default_db.exists()  # default path untouched
