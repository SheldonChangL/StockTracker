"""Typer root command tree for the tsic CLI.

This module assembles the top-level command tree so that ``python -m tsic``
exposes every feature area as a subcommand. The concrete behaviour of each
subcommand is delivered by its own feature story; here they are registered as
stubs so the command tree, ``--help`` output, and global flags work in a clean
environment.
"""

from __future__ import annotations

from dataclasses import dataclass

import typer

from tsic import __version__
from tsic.commandline.analyze_cmd import analyze as analyze_command
from tsic.commandline.db_cmd import db_app
from tsic.commandline.fetch_cmd import fetch as fetch_command
from tsic.commandline.query_cmd import query as query_command
from tsic.commandline.watch_cmd import watch_app

#: Help text shown at the root of the command tree.
_ROOT_HELP = "tsic — StockTracker interactive console."


@dataclass
class GlobalOptions:
    """Verbosity state shared with subcommands via the Typer context."""

    quiet: bool = False
    verbose: bool = False


app = typer.Typer(
    name="tsic",
    help=_ROOT_HELP,
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main_callback(
    ctx: typer.Context,
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Suppress non-essential output."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Emit additional diagnostic output."
    ),
) -> None:
    """Root callback storing global verbosity flags on the context."""
    ctx.obj = GlobalOptions(quiet=quiet, verbose=verbose)


def _stub(ctx: typer.Context, name: str) -> None:
    """Emit a placeholder notice for a not-yet-implemented subcommand."""
    opts: GlobalOptions = ctx.obj or GlobalOptions()
    if not opts.quiet:
        typer.echo(f"tsic {name}: not implemented yet (v{__version__}).")


#: ``tsic fetch`` is delivered by its own module (Story 3.8); register it here.
app.command(name="fetch")(fetch_command)

#: ``tsic query`` is delivered by its own module (Story 4.2); register it here.
app.command(name="query")(query_command)

#: ``tsic analyze`` is delivered by its own module (Story 5.4); register it here.
app.command(name="analyze")(analyze_command)


app.add_typer(db_app, name="db")

#: ``tsic watch`` is delivered by its own module (Story 6.2); register it here.
app.add_typer(watch_app, name="watch")


@app.command()
def schedule(ctx: typer.Context) -> None:
    """Manage scheduled jobs."""
    _stub(ctx, "schedule")


@app.command()
def tui(ctx: typer.Context) -> None:
    """Launch the interactive terminal UI."""
    _stub(ctx, "tui")


def get_app() -> typer.Typer:
    """Return the configured Typer application."""
    return app


def main() -> None:
    """Console entrypoint invoking the Typer command tree."""
    app()


if __name__ == "__main__":
    main()
