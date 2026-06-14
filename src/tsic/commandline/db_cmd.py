"""The ``tsic db`` command group: local database maintenance (Story 2.5).

Currently hosts ``db clean <symbol>``, which removes all of a symbol's stored
records after an explicit confirmation. The destructive action defaults to *no*:
an empty answer (just Enter) or anything other than ``y`` cancels and leaves the
database untouched, so a mistyped command never deletes data by accident.
"""

from __future__ import annotations

from pathlib import Path

import typer

from tsic.storage import database, maintenance, migrations

db_app = typer.Typer(
    name="db",
    help="Manage the local database.",
    no_args_is_help=True,
    add_completion=False,
)


@db_app.command()
def clean(
    symbol: str = typer.Argument(..., help="Stock symbol whose data to delete."),
    db_path: Path | None = typer.Option(
        None,
        "--db-path",
        help="Override the database path (defaults to ~/.tsic/data.db).",
    ),
) -> None:
    """Delete every stored record for SYMBOL after confirmation."""
    conn = database.connect(db_path)
    try:
        migrations.migrate(conn)
        count = maintenance.count_symbol_records(conn, symbol)

        confirmed = typer.confirm(
            f"將刪除 {symbol} 共 {count} 筆記錄，確認？(y/N)",
            default=False,
            show_default=False,
        )
        if not confirmed:
            typer.echo(f"已取消，未刪除 {symbol} 的任何資料。")
            return

        deleted = maintenance.delete_symbol(conn, symbol)
        typer.echo(f"已刪除 {symbol} 共 {deleted} 筆記錄。")
    finally:
        conn.close()
