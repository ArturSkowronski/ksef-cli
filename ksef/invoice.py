"""ksef invoice subcommands: generate, send, status, get, list."""

from __future__ import annotations

import base64
import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import config
from .client import KSeFClient, KSeFError
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
    """Convert a PDF/image/XML file to KSeF FA(2) XML without sending."""
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
        # Print to stdout
        sys.stdout.buffer.write(xml_bytes)


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------


@app.command()
def send(
    file: Path = typer.Argument(..., help="PDF, image, or XML invoice file to send"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Poll for processing status"),
) -> None:
    """Generate (if needed) and send an invoice to KSeF."""
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

    b64 = base64.b64encode(xml_bytes).decode("utf-8")
    # Compute MD5 hash for integrity
    import hashlib
    md5 = hashlib.md5(xml_bytes).hexdigest()

    payload = {
        "invoiceHash": {
            "hashSHA": {
                "algorithm": "SHA-256",
                "encoding": "Base64",
                "value": base64.b64encode(hashlib.sha256(xml_bytes).digest()).decode(),
            },
            "fileSize": len(xml_bytes),
        },
        "invoicePayload": {
            "type": "plain",
            "invoiceBody": b64,
        },
    }

    with KSeFClient(session_token=session_token) as client:
        try:
            result = client.send_invoice(payload)
        except KSeFError as exc:
            err_console.print(f"[red]Send failed: {exc}[/red]")
            raise typer.Exit(1)

    ref = result.get("referenceNumber", "")
    console.print(f"[green]Invoice sent.[/green]")
    console.print(f"  Reference: {ref}")

    if wait and ref:
        _poll_status(session_token, ref)


def _poll_status(session_token: str, ref: str) -> None:
    console.print(f"[dim]Polling for processing status...[/dim]")
    start = time.time()
    with KSeFClient(session_token=session_token) as client:
        while time.time() - start < POLL_TIMEOUT:
            try:
                result = client.invoice_status(ref)
            except KSeFError as exc:
                err_console.print(f"[yellow]Status check error: {exc}[/yellow]")
                break

            code = result.get("processingCode", 0)
            desc = result.get("processingDescription", "")

            if code == 200:
                ksef_ref = result.get("elementReferenceNumber", ref)
                console.print(f"[green]Processed. KSeF reference: {ksef_ref}[/green]")
                return
            elif code >= 400:
                err_console.print(f"[red]Processing failed ({code}): {desc}[/red]")
                return

            console.print(f"  [dim]{desc} ({code})...[/dim]")
            time.sleep(POLL_INTERVAL)

    console.print(f"[yellow]Timed out waiting for processing. Reference: {ref}[/yellow]")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status(
    reference: str = typer.Argument(..., help="Invoice reference number"),
) -> None:
    """Check the processing status of a sent invoice."""
    session_token = config.require_session()

    with KSeFClient(session_token=session_token) as client:
        try:
            result = client.invoice_status(reference)
        except KSeFError as exc:
            err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

    table = Table(title=f"Invoice Status: {reference}", show_header=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Processing Code", str(result.get("processingCode", "")))
    table.add_row("Description", result.get("processingDescription", ""))
    ksef_ref = result.get("elementReferenceNumber", "")
    if ksef_ref:
        table.add_row("KSeF Reference", ksef_ref)
    console.print(table)


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@app.command()
def get(
    reference: str = typer.Argument(..., help="Invoice reference number"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output file path"),
) -> None:
    """Download an invoice XML by reference number."""
    session_token = config.require_session()

    with KSeFClient(session_token=session_token) as client:
        try:
            content = client.get_invoice(reference)
        except KSeFError as exc:
            err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

    if out:
        out.write_bytes(content)
        console.print(f"[green]Invoice saved to {out}[/green]")
    else:
        sys.stdout.buffer.write(content)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command(name="list")
def list_invoices(
    date_from: Optional[str] = typer.Option(None, "--date-from", help="Start date YYYY-MM-DD"),
    date_to: Optional[str] = typer.Option(None, "--date-to", help="End date YYYY-MM-DD"),
) -> None:
    """List invoices in the KSeF system."""
    session_token = config.require_session()

    from datetime import date, datetime

    today = date.today()
    if not date_from:
        date_from = today.replace(day=1).isoformat()
    if not date_to:
        date_to = today.isoformat()

    payload = {
        "queryCriteria": {
            "subjectType": "subject1",
            "type": "incremental",
            "acquisitionTimestampThresholdFrom": f"{date_from}T00:00:00.000Z",
            "acquisitionTimestampThresholdTo": f"{date_to}T23:59:59.999Z",
        }
    }

    with KSeFClient(session_token=session_token) as client:
        try:
            result = client.query_invoice(payload)
        except KSeFError as exc:
            err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

    query_id = result.get("querySessionId", "")
    if not query_id:
        err_console.print("[red]No query session ID returned.[/red]")
        raise typer.Exit(1)

    # Poll for query results
    start = time.time()
    with KSeFClient(session_token=session_token) as client:
        while time.time() - start < 60:
            try:
                status_result = client.query_invoice_status(query_id)
            except KSeFError as exc:
                err_console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1)

            if status_result.get("queryStatus") == "COMPLETED":
                break
            time.sleep(2)

    invoices = status_result.get("invoiceHeaderList", [])
    if not invoices:
        console.print("[dim]No invoices found for the given period.[/dim]")
        return

    table = Table(title=f"Invoices ({date_from} → {date_to})")
    table.add_column("KSeF Reference")
    table.add_column("Invoice Number")
    table.add_column("Date")
    table.add_column("Gross")
    table.add_column("Currency")

    for inv in invoices:
        table.add_row(
            inv.get("ksefReferenceNumber", ""),
            inv.get("invoiceReferenceNumber", ""),
            inv.get("acquisitionTimestamp", "")[:10],
            str(inv.get("gross", "")),
            inv.get("currency", "PLN"),
        )

    console.print(table)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_xml(file: Path) -> bytes:
    """Convert file to FA(2) XML bytes. If already XML, return as-is."""
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
