"""The ``tsic db`` command group: local database maintenance (Stories 2.5, 2.6).

Hosts ``db clean <symbol>``, which removes all of a symbol's stored records
after an explicit confirmation (the destructive action defaults to *no*: an
empty answer or anything other than ``y`` cancels), and ``db status``, a
read-only overview of the local cache (file size, tracked-symbol count, and
each symbol's latest stored date). Both run through the real connect/migrate
path, so invoking either against a missing database creates and migrates it.
"""

from __future__ import annotations

from pathlib import Path

import typer

from tsic import settings
from tsic.storage import database, maintenance, migrations, summary

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


def _human_size(num_bytes: int) -> str:
    """Render a byte count as a short human-readable string (e.g. ``12.3 KB``)."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            precision = 0 if unit == "B" else 1
            return f"{size:.{precision}f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


@db_app.command()
def status(
    db_path: Path | None = typer.Option(
        None,
        "--db",
        "--db-path",
        help="Override the database path (defaults to ~/.tsic/data.db).",
    ),
) -> None:
    """Show a read-only overview of the local database."""
    resolved = Path(db_path) if db_path is not None else settings.default_db_path()

    conn = database.connect(db_path)
    try:
        migrations.migrate(conn)
        symbols = summary.symbol_latest_dates(conn)
    finally:
        conn.close()

    size_bytes = resolved.stat().st_size if resolved.exists() else 0
    typer.echo(f"資料庫：{resolved}")
    typer.echo(f"大小：{_human_size(size_bytes)}（{size_bytes} bytes）")

    if not symbols:
        typer.echo("目前 0 檔追蹤。")
        return

    typer.echo(f"追蹤股票數：{len(symbols)}")
    for sym, latest in symbols:
        typer.echo(f"  {sym}  最新資料日期：{latest}")
