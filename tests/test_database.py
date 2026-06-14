"""Tests for SQLite connection initialization (Story 2.1)."""

import logging
import os
import stat
from pathlib import Path

import pytest

from tsic import settings
from tsic.storage import database

posix_only = pytest.mark.skipif(
    os.name != "posix", reason="file-mode bits are POSIX-only"
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_connect_creates_dir_and_file(tmp_path: Path) -> None:
    """AC-1: opening a connection auto-creates the directory and db file."""
    db_path = tmp_path / "nested" / "data.db"
    conn = database.connect(db_path)
    try:
        assert db_path.parent.is_dir()
        assert db_path.exists()
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        conn.close()


def test_journal_mode_is_wal(tmp_path: Path) -> None:
    """AC-2: PRAGMA journal_mode reports wal for a file-backed database."""
    conn = database.connect(tmp_path / "data.db")
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
    finally:
        conn.close()


@posix_only
def test_new_file_permissions_are_0o600(tmp_path: Path) -> None:
    """AC-3: a freshly created db file is owner-only (0o600)."""
    db_path = tmp_path / "data.db"
    conn = database.connect(db_path)
    try:
        assert _mode(db_path) == 0o600
    finally:
        conn.close()


@posix_only
def test_new_file_does_not_log_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """AC-3/AC-4: creating a new db tightens perms silently (no warning)."""
    with caplog.at_level(logging.WARNING, logger=database.logger.name):
        conn = database.connect(tmp_path / "data.db")
        conn.close()
    assert caplog.records == []


@posix_only
def test_loose_permissions_repaired_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """AC-4: reopening a 0o644 db restores 0o600 and logs a warning."""
    db_path = tmp_path / "data.db"
    database.connect(db_path).close()
    db_path.chmod(0o644)

    with caplog.at_level(logging.WARNING, logger=database.logger.name):
        conn = database.connect(db_path)
        conn.close()

    assert _mode(db_path) == 0o600
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "permissions" in warnings[0].getMessage().lower()


def test_memory_path_is_supported(tmp_path: Path) -> None:
    """AC-5: ':memory:' opens a usable transient db without touching disk."""
    conn = database.connect(":memory:")
    try:
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.execute("INSERT INTO t (id) VALUES (1)")
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    finally:
        conn.close()
    assert not list(tmp_path.iterdir())


def test_default_path_is_injected_from_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-5: a None path falls back to settings.default_db_path()."""
    db_path = tmp_path / "tsic" / "data.db"
    monkeypatch.setattr(settings, "default_db_path", lambda: db_path)
    conn = database.connect()
    try:
        assert db_path.exists()
    finally:
        conn.close()
