"""SQLite connection initialization for tsic local state.

This module owns the single entry point for opening the local database. It
guarantees that, on first use, the ``~/.tsic/`` directory and ``data.db`` file
are created automatically, that the connection runs in WAL mode (per ADR-1's
write-serialization decision), and that on POSIX platforms the database file is
only readable and writable by its owner (mode ``0o600``).

The path is injectable so tests can target a temporary location or an in-memory
database (``:memory:``).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import stat
from pathlib import Path

from tsic import settings

logger = logging.getLogger(__name__)

#: Owner-only read/write; no group or other access.
SECURE_MODE = 0o600

#: Sentinel path for an in-memory database that is never persisted to disk.
MEMORY_PATH = ":memory:"

#: Milliseconds a writer waits on a locked database before raising.
_BUSY_TIMEOUT_MS = 5000

#: POSIX is the only family where file-mode bits are meaningful here.
_IS_POSIX = os.name == "posix"


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open the local SQLite database, initializing it on first use.

    Args:
        db_path: Target database path. ``None`` uses
            :func:`tsic.settings.default_db_path`. The literal ``":memory:"``
            opens a transient in-memory database (no directory or file is
            created, and no permission handling is applied).

    Returns:
        An open :class:`sqlite3.Connection` configured for WAL mode.
    """
    if db_path is None:
        db_path = settings.default_db_path()

    if _is_memory(db_path):
        conn = sqlite3.connect(MEMORY_PATH)
        _apply_pragmas(conn)
        return conn

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    newly_created = not path.exists()

    conn = sqlite3.connect(str(path))
    _apply_pragmas(conn)

    if _IS_POSIX:
        _enforce_permissions(path, newly_created=newly_created)

    return conn


def _is_memory(db_path: str | Path) -> bool:
    """Return ``True`` if ``db_path`` denotes the in-memory database."""
    return isinstance(db_path, str) and db_path == MEMORY_PATH


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Configure WAL journaling, foreign keys, and lock-wait behavior."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")


def _enforce_permissions(path: Path, *, newly_created: bool) -> None:
    """Ensure the database file is ``0o600``, repairing it if necessary.

    A freshly created file is tightened silently. An existing file whose mode
    differs from ``0o600`` is corrected and a warning is logged, so an operator
    can notice that the database had been left more permissive than intended.
    """
    current_mode = stat.S_IMODE(path.stat().st_mode)
    if current_mode == SECURE_MODE:
        return

    path.chmod(SECURE_MODE)
    if not newly_created:
        logger.warning(
            "Repaired permissions on %s from %o to %o",
            path,
            current_mode,
            SECURE_MODE,
        )
