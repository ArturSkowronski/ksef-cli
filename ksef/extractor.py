"""PDF/image → InvoiceData extraction.

Primary: pdfplumber text extraction + heuristic parser.
Fallback: Claude API multimodal extraction when confidence is low.
"""

from __future__ import annotations

import base64
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from rich.console import Console

from .models import BuyerData, InvoiceData, LineItem, SellerData

console = Console()
err_console = Console(stderr=True)

# Confidence threshold below which we invoke the Claude fallback
CONFIDENCE_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_from_file(path: Path) -> InvoiceData:
    """Extract invoice data from a PDF or image file."""
    suffix = path.suffix.lower()

    if suffix == ".xml":
        raise ValueError("XML files should be passed directly; no extraction needed.")

    if suffix == ".pdf":
        return _extract_from_pdf(path)

    # Image formats
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif"}:
        return _extract_from_image(path)

    raise ValueError(f"Unsupported file type: {suffix}")


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------


def _extract_from_pdf(path: Path) -> InvoiceData:
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber is not installed. Run: pip install pdfplumber")

    text_pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            text_pages.append(text)

    full_text = "\n".join(text_pages)

    if not full_text.strip():
        # Image-only PDF — fall back to Claude
        err_console.print("[yellow]PDF appears to be image-only; using Claude fallback.[/yellow]")
        return _extract_via_claude_pdf(path)

    data, confidence = _heuristic_parse(full_text)

    if confidence < CONFIDENCE_THRESHOLD:
        err_console.print(
            f"[yellow]Extraction confidence low ({confidence:.0%}). "
            "Using Claude API for better results.[/yellow]"
        )
        data = _extract_via_claude_pdf(path)
    elif confidence < 0.8:
        err_console.print(
            f"[yellow]Extraction confidence: {confidence:.0%}. "
            "Review generated XML before sending.[/yellow]"
        )

    return data


# ---------------------------------------------------------------------------
# Heuristic parser
# ---------------------------------------------------------------------------


def _heuristic_parse(text: str) -> tuple[InvoiceData, float]:
    """Parse plain text extracted from a PDF into InvoiceData.

    Returns (InvoiceData, confidence) where confidence ∈ [0, 1].
    """
    confidence_points = 0
    max_points = 6

    # --- Invoice number ---
    inv_num = _find_invoice_number(text)
    if inv_num:
        confidence_points += 1

    # --- Dates ---
    issue_date = _find_date(text, r"(?:data\s+wystawienia|issue\s+date)[:\s]*(\d{4}-\d{2}-\d{2}|\d{2}[./]\d{2}[./]\d{4})")
    if not issue_date:
        issue_date = _find_first_date(text)
    if issue_date:
        confidence_points += 1

    # --- NIP numbers ---
    nips = _find_nips(text)
    seller_nip = nips[0] if nips else ""
    buyer_nip = nips[1] if len(nips) > 1 else None
    if seller_nip:
        confidence_points += 1

    # --- Names / addresses (simplified) ---
    seller_name, buyer_name = _find_parties(text)
    if seller_name:
        confidence_points += 1

    # --- Line items ---
    items = _find_line_items(text)
    if items:
        confidence_points += 1

    # --- Totals ---
    total_gross = _find_total(text)
    if total_gross:
        confidence_points += 1

    # Compute totals from items if not found
    if not total_gross and items:
        total_gross = sum(i.gross_amount for i in items)
    if total_gross is None:
        total_gross = Decimal("0")

    total_net = sum(i.net_amount for i in items) if items else Decimal("0")
    total_vat = total_gross - total_net

    seller = SellerData(nip=seller_nip, name=seller_name or "")
    buyer = BuyerData(nip=buyer_nip, name=buyer_name or "")

    data = InvoiceData(
        invoice_number=inv_num or "UNKNOWN",
        issue_date=issue_date or date.today(),
        seller=seller,
        buyer=buyer,
        items=items,
        total_net=total_net,
        total_vat=total_vat,
        total_gross=total_gross,
        extraction_confidence=confidence_points / max_points,
        raw_text=text,
    )

    return data, data.extraction_confidence


def _find_invoice_number(text: str) -> str:
    patterns = [
        r"(?:faktura\s+(?:VAT\s+)?nr|invoice\s+(?:no\.?|number)[:\s]*)([A-Z0-9\/\-]+)",
        r"(?:nr\s+faktury|nr)[:\s]*([A-Z0-9\/\-]+)",
        r"FV[\/\-]?\d+[\/\-]?\d*",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1) if m.lastindex else m.group(0)
    return ""


def _find_date(text: str, pattern: str) -> Optional[date]:
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        return _parse_date(m.group(1))
    return None


def _find_first_date(text: str) -> Optional[date]:
    for pat in [r"\d{4}-\d{2}-\d{2}", r"\d{2}\.\d{2}\.\d{4}", r"\d{2}/\d{2}/\d{4}"]:
        m = re.search(pat, text)
        if m:
            return _parse_date(m.group(0))
    return None


def _parse_date(s: str) -> Optional[date]:
    for fmt in ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"]:
        try:
            return date.fromisoformat(s) if fmt == "%Y-%m-%d" else __import__("datetime").datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _find_nips(text: str) -> list[str]:
    return re.findall(r"\b(\d{10})\b", text)


def _find_parties(text: str) -> tuple[str, str]:
    """Very rough heuristic to find seller and buyer names."""
    seller = ""
    buyer = ""
    # Look for sprzedawca/nabywca sections
    m = re.search(r"(?:sprzedawca|seller)[:\s]*([^\n]+)", text, re.IGNORECASE)
    if m:
        seller = m.group(1).strip()
    m = re.search(r"(?:nabywca|buyer|odbiorca)[:\s]*([^\n]+)", text, re.IGNORECASE)
    if m:
        buyer = m.group(1).strip()
    return seller, buyer


def _find_line_items(text: str) -> list[LineItem]:
    """Extract table rows that look like invoice line items."""
    items: list[LineItem] = []
    # Pattern: name, qty, unit, net price, vat rate, net amount, vat, gross
    # This is a simplified heuristic
    pattern = re.compile(
        r"^(.+?)\s+"  # name
        r"(\d+(?:[.,]\d+)?)\s+"  # quantity
        r"(szt|usł|godz|m2|kg|l|mb|kpl)\.?\s+"  # unit
        r"(\d+(?:[.,]\d+)?)\s+"  # unit net price
        r"(\d+)\s*%?\s+"  # vat rate
        r"(\d+(?:[.,]\d+)?)\s+"  # net amount
        r"(\d+(?:[.,]\d+)?)\s+"  # vat amount
        r"(\d+(?:[.,]\d+)?)",  # gross amount
        re.MULTILINE | re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        try:
            items.append(
                LineItem(
                    name=m.group(1).strip(),
                    unit=m.group(3),
                    quantity=_dec(m.group(2)),
                    unit_price_net=_dec(m.group(4)),
                    vat_rate=m.group(5),
                    net_amount=_dec(m.group(6)),
                    vat_amount=_dec(m.group(7)),
                    gross_amount=_dec(m.group(8)),
                )
            )
        except (InvalidOperation, IndexError):
            continue
    return items


def _find_total(text: str) -> Optional[Decimal]:
    patterns = [
        r"(?:razem\s+do\s+zap[łl]aty|total\s+gross|kwota\s+do\s+zap[łl]aty)[:\s]*(\d+(?:[.,]\d+)?)",
        r"(?:suma|razem|total)[:\s]*(\d+(?:[.,]\d+)?)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return _dec(m.group(1))
    return None


def _dec(s: str) -> Decimal:
    return Decimal(s.replace(",", "."))


# ---------------------------------------------------------------------------
# Claude API fallback
# ---------------------------------------------------------------------------


def _extract_via_claude_pdf(path: Path) -> InvoiceData:
    """Use Claude API with multimodal input to extract invoice data from a PDF/image."""
    import anthropic

    client = anthropic.Anthropic()

    # Encode the file as base64
    raw = path.read_bytes()
    b64 = base64.standard_b64encode(raw).decode("utf-8")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        media_type = "application/pdf"
        source_type = "document"
    else:
        media_type_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        media_type = media_type_map.get(suffix, "image/png")
        source_type = "image"

    prompt = """Extract invoice data from this document and return a JSON object with these fields:
{
  "invoice_number": "string",
  "issue_date": "YYYY-MM-DD",
  "sale_date": "YYYY-MM-DD or null",
  "due_date": "YYYY-MM-DD or null",
  "seller": {
    "nip": "10-digit string",
    "name": "string",
    "address": "string",
    "postal_code": "string",
    "city": "string",
    "country": "PL"
  },
  "buyer": {
    "nip": "10-digit string or null",
    "name": "string",
    "address": "string",
    "postal_code": "string",
    "city": "string",
    "country": "PL"
  },
  "items": [
    {
      "name": "string",
      "unit": "string",
      "quantity": "number as string",
      "unit_price_net": "number as string",
      "vat_rate": "23|8|5|0|zw|np",
      "net_amount": "number as string",
      "vat_amount": "number as string",
      "gross_amount": "number as string"
    }
  ],
  "total_net": "number as string",
  "total_vat": "number as string",
  "total_gross": "number as string",
  "currency": "PLN",
  "notes": "string or empty"
}
Return only the JSON, no explanation."""

    if source_type == "document":
        content = [
            {
                "type": "document",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            },
            {"type": "text", "text": prompt},
        ]
    else:
        content = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            },
            {"type": "text", "text": prompt},
        ]

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )

    text = next(
        (block.text for block in response.content if block.type == "text"), ""
    )

    # Parse the JSON response
    import json

    # Strip markdown code fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())

    data_dict = json.loads(text)
    return _dict_to_invoice_data(data_dict)


def _extract_via_claude_image(path: Path) -> InvoiceData:
    """Alias for image extraction via Claude."""
    return _extract_via_claude_pdf(path)


def _extract_from_image(path: Path) -> InvoiceData:
    return _extract_via_claude_pdf(path)


def _dict_to_invoice_data(d: dict) -> InvoiceData:
    """Convert a dict (from Claude JSON) to InvoiceData."""
    from datetime import datetime

    def parse_date(s: Optional[str]) -> Optional[date]:
        if not s:
            return None
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None

    seller = SellerData(
        nip=d.get("seller", {}).get("nip", ""),
        name=d.get("seller", {}).get("name", ""),
        address=d.get("seller", {}).get("address", ""),
        postal_code=d.get("seller", {}).get("postal_code", ""),
        city=d.get("seller", {}).get("city", ""),
        country=d.get("seller", {}).get("country", "PL"),
    )
    buyer = BuyerData(
        nip=d.get("buyer", {}).get("nip") or None,
        name=d.get("buyer", {}).get("name", ""),
        address=d.get("buyer", {}).get("address", ""),
        postal_code=d.get("buyer", {}).get("postal_code", ""),
        city=d.get("buyer", {}).get("city", ""),
        country=d.get("buyer", {}).get("country", "PL"),
    )
    items = []
    for it in d.get("items", []):
        try:
            items.append(
                LineItem(
                    name=it.get("name", ""),
                    unit=it.get("unit", "szt."),
                    quantity=Decimal(str(it.get("quantity", "1"))),
                    unit_price_net=Decimal(str(it.get("unit_price_net", "0"))),
                    vat_rate=str(it.get("vat_rate", "23")),
                    net_amount=Decimal(str(it.get("net_amount", "0"))),
                    vat_amount=Decimal(str(it.get("vat_amount", "0"))),
                    gross_amount=Decimal(str(it.get("gross_amount", "0"))),
                )
            )
        except (InvalidOperation, KeyError):
            continue

    issue_date = parse_date(d.get("issue_date")) or date.today()

    return InvoiceData(
        invoice_number=d.get("invoice_number", "UNKNOWN"),
        issue_date=issue_date,
        sale_date=parse_date(d.get("sale_date")),
        due_date=parse_date(d.get("due_date")),
        seller=seller,
        buyer=buyer,
        items=items,
        total_net=Decimal(str(d.get("total_net", "0"))),
        total_vat=Decimal(str(d.get("total_vat", "0"))),
        total_gross=Decimal(str(d.get("total_gross", "0"))),
        currency=d.get("currency", "PLN"),
        notes=d.get("notes", ""),
        extraction_confidence=0.9,  # Claude extraction is high confidence
    )
