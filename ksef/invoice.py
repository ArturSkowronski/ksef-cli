"""ksef invoice subcommands: generate, send, status, get, list.

KSeF 2.0 session-based workflow:
  1. Fetch KSeF public key
  2. Generate AES-256 key + IV
  3. Encrypt AES key with RSA-OAEP → base64
  4. Open session (POST /sessions/online)
  5. Encrypt invoice XML with AES-256-CBC
  6. Send encrypted invoice in session
  7. Close session
  8. Poll for processing status
"""

from __future__ import annotations

import base64
import hashlib
import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import config
from .client import KSeFClient, KSeFError
from .crypto import encrypt_aes_key, encrypt_invoice, generate_session_keys
from .extractor import extract_from_file
from .xml_builder import build_xml, validate_xml

app = typer.Typer(help="Manage KSeF invoices.")
console = Console()
err_console = Console(stderr=True)

POLL_INTERVAL = 3  # seconds
POLL_TIMEOUT = 30  # seconds


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


@app.command()
def generate(
    file: Path = typer.Argument(..., help="PDF, image, or existing XML invoice file"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output XML file path"),
) -> None:
    """Convert a PDF/image/XML file to KSeF FA(3) XML without sending."""
    if not file.exists():
        err_console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    xml_bytes = _to_xml(file)

    errors = validate_xml(xml_bytes)
    if errors:
        err_console.print("[yellow]XSD validation warnings:[/yellow]")
        for e in errors:
            err_console.print(f"  [yellow]{e}[/yellow]")

    if out:
        out.write_bytes(xml_bytes)
        console.print(f"[green]XML written to {out}[/green]")
    else:
        sys.stdout.buffer.write(xml_bytes)


# ---------------------------------------------------------------------------
# send (KSeF 2.0 session-based workflow)
# ---------------------------------------------------------------------------


@app.command()
def send(
    file: Path = typer.Argument(..., help="PDF, image, or XML invoice file to send"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Poll for processing status"),
) -> None:
    """Generate (if needed) and send an invoice to KSeF via session workflow."""
    if not file.exists():
        err_console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    session_token = config.require_session()
    xml_bytes = _to_xml(file)

    errors = validate_xml(xml_bytes)
    if errors:
        err_console.print("[yellow]XSD validation warnings (sending anyway):[/yellow]")
        for e in errors:
            err_console.print(f"  [yellow]{e}[/yellow]")

    with KSeFClient(access_token=session_token) as client:
        # Step 1: Fetch KSeF public key
        try:
            pk_resp = client.get_public_key()
        except KSeFError as exc:
            err_console.print(f"[red]Failed to fetch public key: {exc}[/red]")
            raise typer.Exit(1)

        from .auth import _extract_public_key
        public_key_pem = _extract_public_key(pk_resp, usage="SymmetricKeyEncryption")
        if not public_key_pem:
            # Fallback: try token encryption key
            public_key_pem = _extract_public_key(pk_resp, usage="KsefTokenEncryption")
        if not public_key_pem:
            err_console.print("[red]Could not extract public key from API response.[/red]")
            raise typer.Exit(1)

        # Step 2: Generate session encryption keys
        aes_key, iv = generate_session_keys()

        # Step 3: Encrypt AES key with RSA
        encrypted_key_b64 = encrypt_aes_key(aes_key, public_key_pem)
        iv_b64 = base64.b64encode(iv).decode("utf-8")

        # Step 4: Open session
        try:
            session_resp = client.open_session(
                form_code={"systemCode": "FA", "schemaVersion": "1-0E", "value": "106"},
                encryption={
                    "encryptedSymmetricKey": encrypted_key_b64,
                    "initializationVector": iv_b64,
                },
            )
        except KSeFError as exc:
            err_console.print(f"[red]Failed to open session: {exc}[/red]")
            raise typer.Exit(1)

        session_ref = session_resp.get("referenceNumber", "")
        if not session_ref:
            err_console.print(f"[red]No session reference in response: {session_resp}[/red]")
            raise typer.Exit(1)

        console.print(f"[dim]Session opened: {session_ref}[/dim]")

        # Step 5: Encrypt invoice
        encrypted_bytes = encrypt_invoice(xml_bytes, aes_key, iv)

        # Step 6: Build payload with hashes
        plain_hash = base64.b64encode(hashlib.sha256(xml_bytes).digest()).decode()
        encrypted_hash = base64.b64encode(hashlib.sha256(encrypted_bytes).digest()).decode()
        encrypted_content_b64 = base64.b64encode(encrypted_bytes).decode()

        invoice_payload = {
            "invoiceHash": {
                "hashValue": plain_hash,
                "fileSize": len(xml_bytes),
            },
            "encryptedDocumentHash": {
                "hashValue": encrypted_hash,
                "fileSize": len(encrypted_bytes),
            },
            "encryptedDocumentContent": encrypted_content_b64,
        }

        try:
            send_resp = client.send_invoice_in_session(session_ref, invoice_payload)
        except KSeFError as exc:
            err_console.print(f"[red]Send failed: {exc}[/red]")
            # Try to close session even on failure
            try:
                client.close_session(session_ref)
            except KSeFError:
                pass
            raise typer.Exit(1)

        invoice_ref = send_resp.get("referenceNumber", "")
        console.print(f"[green]Invoice sent.[/green]")
        console.print(f"  Invoice reference: {invoice_ref}")

        # Step 7: Close session
        try:
            client.close_session(session_ref)
            console.print(f"[dim]Session closed.[/dim]")
        except KSeFError as exc:
            err_console.print(f"[yellow]Warning: session close failed: {exc}[/yellow]")

        # Step 8: Poll for status
        if wait and invoice_ref:
            _poll_session_status(client, session_ref, invoice_ref)


def _poll_session_status(client: KSeFClient, session_ref: str, invoice_ref: str) -> None:
    """Poll invoice status within a session (150=in progress, 200=ok)."""
    console.print(f"[dim]Polling for processing status...[/dim]")
    start = time.time()
    while time.time() - start < POLL_TIMEOUT:
        try:
            result = client.invoice_status_in_session(session_ref, invoice_ref)
        except KSeFError as exc:
            err_console.print(f"[yellow]Status check error: {exc}[/yellow]")
            break

        code = result.get("processingCode", 0)
        desc = result.get("processingDescription", "")

        if code == 200:
            ksef_number = result.get("ksefNumber", result.get("elementReferenceNumber", invoice_ref))
            console.print(f"[green]Processed. KSeF number: {ksef_number}[/green]")
            return
        elif code >= 400:
            err_console.print(f"[red]Processing failed ({code}): {desc}[/red]")
            return

        console.print(f"  [dim]{desc} ({code})...[/dim]")
        time.sleep(POLL_INTERVAL)

    console.print(f"[yellow]Timed out waiting for processing. Invoice ref: {invoice_ref}[/yellow]")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status(
    reference: str = typer.Argument(..., help="Invoice reference number"),
    session_ref: Optional[str] = typer.Option(None, "--session", "-s", help="Session reference number"),
) -> None:
    """Check the processing status of a sent invoice."""
    session_token = config.require_session()

    with KSeFClient(access_token=session_token) as client:
        try:
            if session_ref:
                result = client.invoice_status_in_session(session_ref, reference)
            else:
                result = client.session_status(reference)
        except KSeFError as exc:
            err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

    table = Table(title=f"Invoice Status: {reference}", show_header=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Processing Code", str(result.get("processingCode", "")))
    table.add_row("Description", result.get("processingDescription", ""))
    ksef_number = result.get("ksefNumber", result.get("elementReferenceNumber", ""))
    if ksef_number:
        table.add_row("KSeF Number", ksef_number)
    console.print(table)


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@app.command()
def get(
    ksef_number: str = typer.Argument(..., help="KSeF invoice number"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output file path"),
    pdf: bool = typer.Option(False, "--pdf", help="Download as PDF (rendered locally from XML)"),
) -> None:
    """Download an invoice XML (or PDF) by KSeF number."""
    session_token = config.require_session()

    with KSeFClient(access_token=session_token) as client:
        try:
            xml_bytes = client.get_invoice_by_ksef(ksef_number)
        except KSeFError as exc:
            err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

    if pdf:
        from .pdf_renderer import render_invoice_pdf
        try:
            content = render_invoice_pdf(xml_bytes)
        except Exception as exc:
            err_console.print(f"[red]PDF rendering failed: {exc}[/red]")
            raise typer.Exit(1)
        # Default output name if not specified
        if not out:
            out = Path(f"{ksef_number}.pdf")
    else:
        content = xml_bytes

    if out:
        out.write_bytes(content)
        console.print(f"[green]Invoice saved to {out}[/green]")
    else:
        sys.stdout.buffer.write(content)


# ---------------------------------------------------------------------------
# list (synchronous query in KSeF 2.0)
# ---------------------------------------------------------------------------


@app.command(name="list")
def list_invoices(
    date_from: Optional[str] = typer.Option(None, "--date-from", help="Start date YYYY-MM-DD"),
    date_to: Optional[str] = typer.Option(None, "--date-to", help="End date YYYY-MM-DD"),
    seller_nip: Optional[str] = typer.Option(None, "--seller-nip", help="Filter by seller NIP"),
    received: bool = typer.Option(False, "--received", "-r", help="List received invoices (subject2) instead of issued"),
) -> None:
    """List invoices in the KSeF system (synchronous query)."""
    session_token = config.require_session()

    from datetime import date as date_type

    today = date_type.today()
    if not date_from:
        date_from = today.replace(day=1).isoformat()
    if not date_to:
        date_to = today.isoformat()

    subject = "subject2" if received else "subject1"
    payload: dict = {
        "subjectType": subject,
        "dateRange": {
            "dateType": "invoicing",
            "from": f"{date_from}T00:00:00.000Z",
            "to": f"{date_to}T23:59:59.999Z",
        },
    }
    if seller_nip:
        payload["sellerNip"] = seller_nip

    all_invoices: list = []
    with KSeFClient(access_token=session_token) as client:
        while True:
            try:
                result = client.query_invoice_metadata(payload)
            except KSeFError as exc:
                err_console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1)

            invoices = result.get("invoices", result.get("invoiceHeaderList", []))
            all_invoices.extend(invoices)

            has_more = result.get("hasMore", False)
            continuation = result.get("_continuationToken")
            if not has_more or not continuation:
                break
            payload["continuationToken"] = continuation

    if not all_invoices:
        console.print("[dim]No invoices found for the given period.[/dim]")
        return

    table = Table(title=f"Invoices ({date_from} → {date_to})")
    table.add_column("KSeF Number")
    table.add_column("Invoice Number")
    table.add_column("Seller" if received else "Buyer")
    table.add_column("Date")
    table.add_column("Net")
    table.add_column("Gross")
    table.add_column("Currency")

    for inv in all_invoices:
        ksef_nr = inv.get("ksefNumber", inv.get("ksefReferenceNumber", ""))
        inv_nr = inv.get("invoiceNumber", inv.get("invoiceReferenceNumber", ""))
        date_val = (inv.get("issueDate") or inv.get("acquisitionTimestamp", "") or "")[:10]
        counterparty = inv.get("seller", {}).get("name", "") if received else inv.get("buyer", {}).get("name", "")
        net = inv.get("netAmount", inv.get("net", ""))
        gross = inv.get("grossAmount", inv.get("gross", ""))
        table.add_row(
            ksef_nr,
            inv_nr,
            counterparty,
            date_val,
            str(net),
            str(gross),
            inv.get("currency", "PLN"),
        )

    console.print(table)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_xml(file: Path) -> bytes:
    """Convert file to FA(3) XML bytes. If already XML, return as-is."""
    if file.suffix.lower() == ".xml":
        return file.read_bytes()

    console.print(f"[dim]Extracting invoice data from {file.name}...[/dim]")
    try:
        invoice_data = extract_from_file(file)
    except Exception as exc:
        err_console.print(f"[red]Extraction failed: {exc}[/red]")
        raise typer.Exit(1)

    if invoice_data.extraction_confidence < 0.5:
        err_console.print(
            f"[yellow]Low confidence extraction ({invoice_data.extraction_confidence:.0%}). "
            "Review the generated XML carefully.[/yellow]"
        )

    return build_xml(invoice_data)
