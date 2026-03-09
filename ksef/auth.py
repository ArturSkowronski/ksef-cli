"""ksef auth subcommands: login, refresh, status.

KSeF API 2.0 token-based authentication flow:
  1. GET  /security/public-key-certificates  → RSA public key
  2. POST /auth/challenge                    → challenge + timestamp
  3. Encrypt "{token}|{timestampMs}" with RSA-OAEP(SHA-256, MGF1) using the public key
  4. POST /auth/ksef-token                   → authenticationToken + referenceNumber
  5. Poll GET /auth/{ref}                    until processingCode == 200 (150 = in progress)
  6. POST /auth/token/redeem                 → accessToken + refreshToken
  7. Save tokens + expiry to config
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import config
from .client import KSeFClient, KSeFError
from .crypto import rsa_encrypt_b64

app = typer.Typer(help="Authenticate with the KSeF API.")
console = Console()
err_console = Console(stderr=True)

_POLL_INTERVAL = 2  # seconds
_POLL_TIMEOUT = 30  # seconds


# ---------------------------------------------------------------------------
# RSA-OAEP encryption helper (delegates to crypto module)
# ---------------------------------------------------------------------------


def _encrypt_token(token: str, timestamp_ms: int, public_key_pem: str) -> str:
    """
    Encrypt "{token}|{timestampMs}" using RSA-OAEP(SHA-256, MGF1(SHA-256))
    with the KSeF public key, and return the Base64-encoded ciphertext.
    """
    payload = f"{token}|{timestamp_ms}".encode("utf-8")
    return rsa_encrypt_b64(payload, public_key_pem)


def _extract_public_key(pk_resp: list | dict, usage: str = "KsefTokenEncryption") -> str | None:
    """
    Extract RSA public key PEM from KSeF certificate response.

    The API returns a list of dicts with:
      - "certificate": base64-encoded X.509 DER certificate
      - "usage": ["KsefTokenEncryption"] or ["SymmetricKeyEncryption"]

    We extract the public key from the X.509 certificate matching the requested usage.
    Also handles legacy response formats (direct publicKey/key/pem fields).
    """
    import base64
    from cryptography import x509

    certs = pk_resp if isinstance(pk_resp, list) else pk_resp.get("certificates", [pk_resp])

    for cert in certs:
        if not isinstance(cert, dict):
            continue

        # Check usage filter
        cert_usage = cert.get("usage", [])
        if cert_usage and usage and usage not in cert_usage:
            continue

        # Try X.509 certificate field first (real API format)
        cert_b64 = cert.get("certificate")
        if cert_b64:
            try:
                cert_der = base64.b64decode(cert_b64)
                x509_cert = x509.load_der_x509_certificate(cert_der)
                from cryptography.hazmat.primitives import serialization
                pub_key_pem = x509_cert.public_key().public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                ).decode("utf-8")
                return pub_key_pem
            except Exception:
                pass

        # Legacy: direct key field
        key = cert.get("publicKey") or cert.get("key") or cert.get("pem")
        if key:
            return key

    return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def login(
    nip: str = typer.Option(..., "--nip", envvar="KSEF_NIP", help="Taxpayer NIP (10 digits)"),
    token: str = typer.Option(..., "--token", envvar="KSEF_TOKEN", help="KSeF authorisation token"),
) -> None:
    """Authenticate and store session token (KSeF API 2.0)."""
    nip = nip.strip()
    token = token.strip()

    with KSeFClient() as client:
        # Step 1: Fetch KSeF public key
        try:
            pk_resp = client.get_public_key()
        except KSeFError as exc:
            err_console.print(f"[red]Failed to fetch public key: {exc}[/red]")
            raise typer.Exit(1)

        # Extract RSA public key from certificates response
        public_key_pem = _extract_public_key(pk_resp, usage="KsefTokenEncryption")
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
        # API returns timestampMs (int) and timestamp (ISO string)
        timestamp_ms = challenge_resp.get("timestampMs") or challenge_resp.get("timestamp")
        if isinstance(timestamp_ms, str):
            try:
                dt = datetime.fromisoformat(timestamp_ms.replace("Z", "+00:00"))
                timestamp_ms = int(dt.timestamp() * 1000)
            except ValueError:
                timestamp_ms = int(time.time() * 1000)
        elif timestamp_ms is None:
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

        # KSeF 2.0: authenticationToken may be nested
        auth_token_data = token_resp.get("authenticationToken", "")
        if isinstance(auth_token_data, dict):
            authentication_token = auth_token_data.get("token", "")
        else:
            authentication_token = auth_token_data
        reference_number = token_resp.get("referenceNumber", "")

        if not authentication_token and not reference_number:
            err_console.print(f"[red]Unexpected token response: {token_resp}[/red]")
            raise typer.Exit(1)

        if not authentication_token:
            err_console.print("[red]No authentication token received.[/red]")
            raise typer.Exit(1)

        # Brief delay before redeem to let server finalize
        time.sleep(1)

        # Step 6: Redeem for access token + refresh token
        try:
            redeem_resp = client.auth_token_redeem(authentication_token)
        except KSeFError as exc:
            err_console.print(f"[red]Token redeem failed: {exc}[/red]")
            raise typer.Exit(1)

    # KSeF 2.0: tokens may be nested objects with token + expiresIn
    access_data = redeem_resp.get("accessToken", "")
    if isinstance(access_data, dict):
        access_token = access_data.get("token", "")
        expires_in = access_data.get("expiresIn", 3600)
        expiry_str = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    else:
        access_token = access_data
        expiry_str = redeem_resp.get("tokenExpiry", "")
        if not expiry_str:
            expiry_str = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    refresh_data = redeem_resp.get("refreshToken", "")
    if isinstance(refresh_data, dict):
        refresh_token_val = refresh_data.get("token", "")
        refresh_expires_in = refresh_data.get("expiresIn", 86400)
        refresh_expiry = (datetime.now(timezone.utc) + timedelta(seconds=refresh_expires_in)).isoformat()
    else:
        refresh_token_val = refresh_data
        refresh_expiry = ""

    if not access_token:
        err_console.print(f"[red]No access token in redeem response: {redeem_resp}[/red]")
        raise typer.Exit(1)

    config.set_values(
        nip=nip,
        token=token,
        session_token=access_token,
        session_expiry=expiry_str,
        refresh_token=refresh_token_val,
        refresh_expiry=refresh_expiry,
    )

    console.print("[green]Logged in successfully.[/green]")
    console.print(f"  NIP: {nip}")
    console.print(f"  Expires: {expiry_str}")
    if refresh_token_val:
        console.print(f"  Refresh token: saved")


@app.command()
def refresh() -> None:
    """Refresh the access token using the stored refresh token."""
    refresh_token_val = config.get("refresh_token")
    if not refresh_token_val:
        err_console.print("[red]No refresh token stored. Run `ksef auth login` first.[/red]")
        raise typer.Exit(1)

    with KSeFClient() as client:
        try:
            resp = client.auth_token_refresh(refresh_token_val)
        except KSeFError as exc:
            err_console.print(f"[red]Token refresh failed: {exc}[/red]")
            raise typer.Exit(1)

    access_data = resp.get("accessToken", "")
    if isinstance(access_data, dict):
        access_token = access_data.get("token", "")
        expires_in = access_data.get("expiresIn", 3600)
        expiry_str = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    else:
        access_token = access_data
        expiry_str = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    new_refresh = resp.get("refreshToken", "")
    if isinstance(new_refresh, dict):
        new_refresh_val = new_refresh.get("token", "")
        refresh_expires_in = new_refresh.get("expiresIn", 86400)
        refresh_expiry = (datetime.now(timezone.utc) + timedelta(seconds=refresh_expires_in)).isoformat()
    else:
        new_refresh_val = new_refresh
        refresh_expiry = ""

    updates = {
        "session_token": access_token,
        "session_expiry": expiry_str,
    }
    if new_refresh_val:
        updates["refresh_token"] = new_refresh_val
        updates["refresh_expiry"] = refresh_expiry

    config.set_values(**updates)
    console.print("[green]Token refreshed.[/green]")
    console.print(f"  Expires: {expiry_str}")


@app.command()
def logout() -> None:
    """Clear local session tokens (KSeF 2.0 has no server-side logout)."""
    config.set_values(
        session_token="",
        session_expiry="",
        refresh_token="",
        refresh_expiry="",
    )
    console.print("[green]Local session cleared.[/green]")


@app.command()
def status() -> None:
    """Show current session info."""
    cfg = config.load()

    table = Table(title="KSeF Session Status", show_header=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("NIP", cfg.get("nip") or "[dim]not set[/dim]")
    table.add_row("Environment", cfg.get("environment", "PRD"))

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

    refresh_token_val = cfg.get("refresh_token", "")
    if refresh_token_val:
        table.add_row("Refresh Token", refresh_token_val[:8] + "..." + refresh_token_val[-4:])
        table.add_row("Refresh Expiry", cfg.get("refresh_expiry", "[dim]unknown[/dim]"))
    else:
        table.add_row("Refresh Token", "[dim]none[/dim]")

    console.print(table)
