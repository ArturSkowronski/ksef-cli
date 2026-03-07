"""ksef auth subcommands: login, logout, status."""

from __future__ import annotations

import base64
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import config
from .client import KSeFClient, KSeFError

app = typer.Typer(help="Authenticate with the KSeF API.")
console = Console()
err_console = Console(stderr=True)


def _sign_challenge(challenge: str, token: str) -> str:
    """
    KSeF auth token signing: SHA-256(challenge || token) encoded as base64.
    The token is the raw authorisation token string.
    """
    payload = (challenge + "|" + token).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return base64.b64encode(digest).decode("utf-8")


@app.command()
def login(
    nip: str = typer.Option(..., "--nip", help="Taxpayer NIP (10 digits)"),
    token: str = typer.Option(..., "--token", help="KSeF authorisation token"),
) -> None:
    """Authenticate and store session token."""
    nip = nip.strip()
    token = token.strip()

    with KSeFClient() as client:
        # Step 1: get challenge
        try:
            challenge_resp = client.authorisation_challenge(nip)
        except KSeFError as exc:
            err_console.print(f"[red]Auth challenge failed: {exc}[/red]")
            raise typer.Exit(1)

        challenge = challenge_resp.get("challenge", "")
        timestamp = challenge_resp.get("timestamp", "")

        if not challenge:
            err_console.print("[red]Unexpected response: missing challenge.[/red]")
            raise typer.Exit(1)

        # Step 2: sign and init token
        signed = _sign_challenge(challenge, token)

        init_payload = {
            "contextIdentifier": {"type": "onip", "identifier": nip},
            "authorisationToken": signed,
        }

        try:
            session_resp = client.init_token(init_payload)
        except KSeFError as exc:
            err_console.print(f"[red]Session init failed: {exc}[/red]")
            raise typer.Exit(1)

    session_token = session_resp.get("sessionToken", {})
    if isinstance(session_token, dict):
        token_value = session_token.get("token", "")
        # KSeF sessions typically last 3600s; use expiry from response if available
        expiry_str = session_token.get("sessionTokenExpiry", "")
    else:
        token_value = str(session_token)
        expiry_str = ""

    if not token_value:
        err_console.print("[red]No session token in response.[/red]")
        raise typer.Exit(1)

    # Default expiry: 1 hour from now
    if not expiry_str:
        expiry_dt = datetime.now(timezone.utc) + timedelta(hours=1)
        expiry_str = expiry_dt.isoformat()

    config.set_values(
        nip=nip,
        token=token,
        session_token=token_value,
        session_expiry=expiry_str,
    )

    console.print(f"[green]Logged in. Session token saved.[/green]")
    console.print(f"  NIP: {nip}")
    console.print(f"  Expires: {expiry_str}")


@app.command()
def logout() -> None:
    """Terminate the current KSeF session."""
    session_token = config.get("session_token")
    if not session_token:
        err_console.print("[yellow]No active session to terminate.[/yellow]")
        raise typer.Exit(0)

    with KSeFClient(session_token=session_token) as client:
        try:
            client.terminate_session()
        except KSeFError as exc:
            # If session is already expired, treat as success
            err_console.print(f"[yellow]Warning: {exc}[/yellow]")

    config.set_values(session_token="", session_expiry="")
    console.print("[green]Logged out.[/green]")


@app.command()
def status() -> None:
    """Show current session info."""
    cfg = config.load()

    table = Table(title="KSeF Session Status", show_header=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("NIP", cfg.get("nip") or "[dim]not set[/dim]")

    session_token = cfg.get("session_token", "")
    if session_token:
        masked = session_token[:8] + "..." + session_token[-4:]
        table.add_row("Session Token", masked)
    else:
        table.add_row("Session Token", "[dim]none[/dim]")

    expiry = cfg.get("session_expiry", "")
    if expiry:
        try:
            exp_dt = datetime.fromisoformat(expiry)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if now < exp_dt:
                remaining = exp_dt - now
                table.add_row(
                    "Expiry",
                    f"{expiry} ([green]{int(remaining.total_seconds() // 60)} min remaining[/green])",
                )
            else:
                table.add_row("Expiry", f"{expiry} ([red]EXPIRED[/red])")
        except ValueError:
            table.add_row("Expiry", expiry)
    else:
        table.add_row("Expiry", "[dim]none[/dim]")

    console.print(table)
