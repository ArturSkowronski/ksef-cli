"""ksef auth subcommands: login, logout, status.

KSeF API v2 token-based authentication flow:
  1. GET  /api/v2/security/public-key-certificates  → RSA public key
  2. POST /api/v2/auth/challenge                    → challenge + timestampMs
  3. Encrypt "{token}|{timestampMs}" with RSA-OAEP(SHA-256, MGF1) using the public key
  4. POST /api/v2/auth/ksef-token                   → authenticationToken + referenceNumber
  5. Poll GET /api/v2/auth/token/status/{ref}        until status == "DONE"
  6. POST /api/v2/auth/token/redeem                  → accessToken (JWT)
  7. Save accessToken + expiry to config
"""

from __future__ import annotations

import base64
import time
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

_POLL_INTERVAL = 2  # seconds
_POLL_TIMEOUT = 30  # seconds


# ---------------------------------------------------------------------------
# RSA-OAEP encryption helper
# ---------------------------------------------------------------------------


def _encrypt_token(token: str, timestamp_ms: int, public_key_pem: str) -> str:
    """
    Encrypt "{token}|{timestampMs}" using RSA-OAEP(SHA-256, MGF1(SHA-256))
    with the KSeF public key, and return the Base64-encoded ciphertext.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    payload = f"{token}|{timestamp_ms}".encode("utf-8")

    # Load the public key — may be PEM or DER base64 depending on the API response
    if public_key_pem.strip().startswith("-----"):
        pub_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    else:
        # Raw base64-DER
        der_bytes = base64.b64decode(public_key_pem)
        pub_key = serialization.load_der_public_key(der_bytes)

    ciphertext = pub_key.encrypt(
        payload,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(ciphertext).decode("utf-8")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def login(
    nip: str = typer.Option(..., "--nip", help="Taxpayer NIP (10 digits)"),
    token: str = typer.Option(..., "--token", help="KSeF authorisation token"),
) -> None:
    """Authenticate and store session token (KSeF API v2)."""
    nip = nip.strip()
    token = token.strip()

    with KSeFClient() as client:
        # Step 1: Fetch KSeF public key
        try:
            pk_resp = client.get_public_key()
        except KSeFError as exc:
            err_console.print(f"[red]Failed to fetch public key: {exc}[/red]")
            raise typer.Exit(1)

        # The API may return a list of certificates; take the first active one
        certs = pk_resp if isinstance(pk_resp, list) else pk_resp.get("certificates", [pk_resp])
        public_key_pem = None
        for cert in certs:
            if isinstance(cert, dict):
                public_key_pem = cert.get("publicKey") or cert.get("key") or cert.get("pem")
            elif isinstance(cert, str):
                public_key_pem = cert
            if public_key_pem:
                break

        if not public_key_pem:
            err_console.print("[red]Could not extract public key from API response.[/red]")
            err_console.print(f"[dim]Response: {pk_resp}[/dim]")
            raise typer.Exit(1)

        # Step 2: Get challenge
        try:
            challenge_resp = client.auth_challenge(nip)
        except KSeFError as exc:
            err_console.print(f"[red]Auth challenge failed: {exc}[/red]")
            raise typer.Exit(1)

        challenge = challenge_resp.get("challenge", "")
        timestamp_ms = challenge_resp.get("timestamp", int(time.time() * 1000))
        if isinstance(timestamp_ms, str):
            # Some responses return ISO string; convert to ms
            try:
                dt = datetime.fromisoformat(timestamp_ms.replace("Z", "+00:00"))
                timestamp_ms = int(dt.timestamp() * 1000)
            except ValueError:
                timestamp_ms = int(time.time() * 1000)

        if not challenge:
            err_console.print("[red]Unexpected response: missing challenge.[/red]")
            raise typer.Exit(1)

        # Step 3: Encrypt token
        try:
            encrypted_token = _encrypt_token(token, timestamp_ms, public_key_pem)
        except Exception as exc:
            err_console.print(f"[red]Token encryption failed: {exc}[/red]")
            raise typer.Exit(1)

        # Step 4: Submit encrypted token
        init_payload = {
            "challenge": challenge,
            "contextIdentifier": {"type": "nip", "value": nip},
            "encryptedToken": encrypted_token,
        }

        try:
            token_resp = client.auth_ksef_token(init_payload)
        except KSeFError as exc:
            err_console.print(f"[red]Token submission failed: {exc}[/red]")
            raise typer.Exit(1)

        authentication_token = token_resp.get("authenticationToken", "")
        reference_number = token_resp.get("referenceNumber", "")

        if not authentication_token and not reference_number:
            err_console.print(f"[red]Unexpected token response: {token_resp}[/red]")
            raise typer.Exit(1)

        # Step 5: Poll for DONE status (if referenceNumber returned)
        if reference_number and not authentication_token:
            console.print("[dim]Waiting for authentication to complete...[/dim]")
            start = time.time()
            while time.time() - start < _POLL_TIMEOUT:
                try:
                    status_resp = client.auth_token_status(reference_number)
                except KSeFError as exc:
                    err_console.print(f"[red]Status poll failed: {exc}[/red]")
                    raise typer.Exit(1)

                processing_code = status_resp.get("processingCode", 0)
                if processing_code == 200:
                    authentication_token = status_resp.get("authenticationToken", "")
                    break
                elif processing_code >= 400:
                    err_console.print(
                        f"[red]Authentication failed ({processing_code}): "
                        f"{status_resp.get('processingDescription', '')}[/red]"
                    )
                    raise typer.Exit(1)

                time.sleep(_POLL_INTERVAL)
            else:
                err_console.print("[red]Timed out waiting for authentication.[/red]")
                raise typer.Exit(1)

        if not authentication_token:
            err_console.print("[red]No authentication token received.[/red]")
            raise typer.Exit(1)

        # Step 6: Redeem for final access token
        try:
            redeem_resp = client.auth_token_redeem(authentication_token)
        except KSeFError as exc:
            err_console.print(f"[red]Token redeem failed: {exc}[/red]")
            raise typer.Exit(1)

    access_token = redeem_resp.get("accessToken", "")
    expiry_str = redeem_resp.get("tokenExpiry", "")

    if not access_token:
        err_console.print(f"[red]No access token in redeem response: {redeem_resp}[/red]")
        raise typer.Exit(1)

    if not expiry_str:
        expiry_dt = datetime.now(timezone.utc) + timedelta(hours=1)
        expiry_str = expiry_dt.isoformat()

    config.set_values(
        nip=nip,
        token=token,
        session_token=access_token,
        session_expiry=expiry_str,
    )

    console.print("[green]Logged in successfully.[/green]")
    console.print(f"  NIP: {nip}")
    console.print(f"  Expires: {expiry_str}")


@app.command()
def logout() -> None:
    """Terminate the current KSeF session."""
    access_token = config.get("session_token")
    if not access_token:
        err_console.print("[yellow]No active session to terminate.[/yellow]")
        raise typer.Exit(0)

    with KSeFClient(access_token=access_token) as client:
        try:
            client.auth_logout()
        except KSeFError as exc:
            err_console.print(f"[yellow]Warning during logout: {exc}[/yellow]")

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
        table.add_row("Access Token", masked)
    else:
        table.add_row("Access Token", "[dim]none[/dim]")

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
