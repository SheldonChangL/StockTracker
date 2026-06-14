"""Versioned schema migrations for the tsic SQLite database (Story 2.2).

A single :func:`migrate` entry point brings a database up to
:data:`SCHEMA_VERSION`. The applied version is recorded in the ``meta`` table
(``schema_version``), so re-running :func:`migrate` on an up-to-date database is
a cheap no-op (idempotency). Future versions add a new ``_apply_vN`` step and
bump :data:`SCHEMA_VERSION`; each step runs only when the stored version is
behind it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

#: Latest schema version this module knows how to produce.
SCHEMA_VERSION = 2

#: DDL for the current schema, kept alongside this module.
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

#: Key under which the applied schema version is stored in ``meta``.
_VERSION_KEY = "schema_version"

#: Default policy seeds inserted at v1 (never overwrites an operator's change).
_V1_META_SEED = {
    "adjust_policy": "raw",
}


def migrate(conn: sqlite3.Connection) -> int:
    """Bring ``conn`` up to :data:`SCHEMA_VERSION`, returning the new version.

    Args:
        conn: An open SQLite connection.

    Returns:
        The schema version after migration (always :data:`SCHEMA_VERSION`).
    """
    _ensure_meta(conn)
    version = _current_version(conn)
    if version >= SCHEMA_VERSION:
        return version

    if version < 1:
        _apply_v1(conn)
    if version < 2:
        _apply_v2(conn)

    _set_version(conn, SCHEMA_VERSION)
    conn.commit()
    return SCHEMA_VERSION


def _ensure_meta(conn: sqlite3.Connection) -> None:
    """Create the ``meta`` table if needed so the version can be read."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS meta ("
        "key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)"
    )


def _current_version(conn: sqlite3.Connection) -> int:
    """Return the stored schema version, or ``0`` if none is recorded."""
    row = conn.execute(
        "SELECT value FROM meta WHERE key = ?", (_VERSION_KEY,)
    ).fetchone()
    return int(row[0]) if row else 0


def _apply_v1(conn: sqlite3.Connection) -> None:
    """Create all v1 tables/indexes and seed default policy flags."""
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.executemany(
        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
        _V1_META_SEED.items(),
    )


def _apply_v2(conn: sqlite3.Connection) -> None:
    """Add ``watchlist.added_at`` for databases created before v2.

    Fresh databases already gain the column from ``schema.sql`` in v1, so the
    ALTER is guarded by a column-existence check to stay idempotent. The
    ``DEFAULT ''`` only satisfies the NOT NULL constraint for any rows that
    predate the column; the repository always writes a real timestamp.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(watchlist)")}
    if "added_at" not in columns:
        conn.execute(
            "ALTER TABLE watchlist ADD COLUMN added_at TEXT NOT NULL DEFAULT ''"
        )


def _set_version(conn: sqlite3.Connection, version: int) -> None:
    """Record ``version`` as the applied schema version (upsert)."""
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_VERSION_KEY, str(version)),
    )
