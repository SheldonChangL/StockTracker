"""The ``tsic watch`` command group: manage the tracked-symbol watchlist
(Story 6.2, FR-22).

This is the *vertical* CLI entry point over :class:`~tsic.storage.repository.
WatchlistRepository` (Story 6.1): it opens and migrates the local database, then
delegates each subcommand to the repository's CRUD methods.

* ``watch add SYMBOL``    — track a symbol (idempotent; re-adding is a no-op).
* ``watch remove SYMBOL`` — stop tracking a symbol (removing an untracked symbol
  is a harmless no-op).
* ``watch list``          — print tracked symbols oldest-first, or a friendly
  empty-state notice when nothing is tracked.

Every subcommand runs through the real connect/migrate path, so invoking any of
them against a missing database creates and migrates it, and all exit ``0`` on
success (AC-1..AC-3).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import typer

from tsic.storage import database, migrations
from tsic.storage.repository import WatchlistRepository

#: Message shown by ``watch list`` when the watchlist holds no symbols (AC-3).
_EMPTY_NOTICE = "觀察清單是空的。"

#: Shared ``--db`` option, mirroring the spelling used by ``query`` / ``db``.
_DB_OPTION = typer.Option(
    None,
    "--db",
    "--db-path",
    help="覆寫資料庫路徑（預設 ~/.tsic/data.db）。",
)

watch_app = typer.Typer(
    name="watch",
    help="管理觀察清單（watchlist）。",
    no_args_is_help=True,
    add_completion=False,
)


def _repository(
    db_path: Path | None,
) -> tuple[WatchlistRepository, sqlite3.Connection]:
    """Open and migrate the database, returning a repository and its connection.

    The caller owns the connection's lifecycle and must close it.
    """
    conn = database.connect(db_path)
    migrations.migrate(conn)
    return WatchlistRepository(conn), conn


@watch_app.command()
def add(
    symbol: str = typer.Argument(..., help="要追蹤的股票代號（例如 2330）。"),
    db_path: Path | None = _DB_OPTION,
) -> None:
    """Add SYMBOL to the watchlist (idempotent)."""
    repo, conn = _repository(db_path)
    try:
        repo.add(symbol)
    finally:
        conn.close()
    typer.echo(f"已加入觀察清單：{symbol}")


@watch_app.command()
def remove(
    symbol: str = typer.Argument(..., help="要移除的股票代號（例如 2330）。"),
    db_path: Path | None = _DB_OPTION,
) -> None:
    """Remove SYMBOL from the watchlist (no-op if not tracked)."""
    repo, conn = _repository(db_path)
    try:
        repo.remove(symbol)
    finally:
        conn.close()
    typer.echo(f"已移出觀察清單：{symbol}")


@watch_app.command(name="list")
def list_(
    db_path: Path | None = _DB_OPTION,
) -> None:
    """List tracked symbols, oldest first (AC-3: empty list is not an error)."""
    repo, conn = _repository(db_path)
    try:
        entries = repo.list()
    finally:
        conn.close()

    if not entries:
        typer.echo(_EMPTY_NOTICE)
        return

    for entry in entries:
        typer.echo(f"{entry.symbol}  加入時間：{entry.added_at}")
