"""Root Typer application wiring all sub-apps."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from . import __version__
from . import auth, invoice
from . import config as cfg_module

app = typer.Typer(
    name="ksef",
    help="KSeF CLI — interact with the Polish National e-Invoice System.",
    no_args_is_help=True,
)
console = Console()

# Register sub-apps
app.add_typer(auth.app, name="auth")
app.add_typer(invoice.app, name="invoice")


# ---------------------------------------------------------------------------
# Config subcommand
# ---------------------------------------------------------------------------

config_app = typer.Typer(help="Manage local ksef-cli configuration.")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show() -> None:
    """Print current configuration (tokens are masked)."""
    from rich.table import Table

    cfg = cfg_module.load()

    table = Table(title="ksef config", show_header=False)
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("nip", cfg.get("nip") or "[dim]not set[/dim]")

    token = cfg.get("token", "")
    if token:
        masked = token[:4] + "****" + token[-2:]
        table.add_row("token", masked)
    else:
        table.add_row("token", "[dim]not set[/dim]")

    session_token = cfg.get("session_token", "")
    if session_token:
        masked = session_token[:8] + "..." + session_token[-4:]
        table.add_row("session_token", masked)
    else:
        table.add_row("session_token", "[dim]none[/dim]")

    table.add_row("session_expiry", cfg.get("session_expiry") or "[dim]none[/dim]")

    console.print(table)


@config_app.command("set")
def config_set(
    nip: Optional[str] = typer.Option(None, "--nip", help="Taxpayer NIP"),
    token: Optional[str] = typer.Option(None, "--token", help="KSeF authorisation token"),
) -> None:
    """Save credentials to config without authenticating."""
    updates: dict[str, str] = {}
    if nip is not None:
        updates["nip"] = nip.strip()
    if token is not None:
        updates["token"] = token.strip()

    if not updates:
        console.print("[yellow]Nothing to set. Use --nip or --token.[/yellow]")
        raise typer.Exit(0)

    cfg_module.set_values(**updates)
    console.print("[green]Config saved.[/green]")


# ---------------------------------------------------------------------------
# Version flag
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"ksef-cli {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Print version and exit.",
    ),
) -> None:
    """KSeF CLI"""
