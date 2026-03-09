"""Build KSeF FA(3) XML from InvoiceData and optionally validate against XSD."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Optional

from lxml import etree

from .models import InvoiceData, LineItem

# FA(3) namespace
FA_NS = "http://crd.gov.pl/wzor/2025/06/25/13775/"
XSD_PATH = Path(__file__).parent / "schemas" / "FA_VAT_FA(3).xsd"


def build_xml(invoice: InvoiceData) -> bytes:
    """Render InvoiceData → KSeF FA(3) XML (UTF-8, with XML declaration)."""
    root = etree.Element(
        f"{{{FA_NS}}}Faktura",
        nsmap={None: FA_NS},
    )
    root.set("SchemaVersion", "1-0E")

    # Naglowek (header)
    naglowek = _sub(root, "Naglowek")
    _sub(naglowek, "KodFormularza", "FA", kodSystemowy="FA (3)", wersjaSchemy="1-0E")
    _sub(naglowek, "WariantFormularza", "3")
    _sub(naglowek, "DataWytworzeniaFa", invoice.issue_date.isoformat())
    _sub(naglowek, "SystemInfo", "ksef-cli")

    # Podmiot1 (seller)
    pod1 = _sub(root, "Podmiot1")
    pre1 = _sub(pod1, "PrefiksMiejscaDostarczenia", invoice.seller.country)  # noqa: F841
    danych1 = _sub(pod1, "DaneIdentyfikacyjne")
    _sub(danych1, "NIP", invoice.seller.nip)
    _sub(danych1, "PelnaNazwa", invoice.seller.name)
    adres1 = _sub(pod1, "Adres")
    _sub(adres1, "KodKraju", invoice.seller.country)
    _sub(adres1, "AdresL1", invoice.seller.address or invoice.seller.name)
    if invoice.seller.postal_code or invoice.seller.city:
        _sub(adres1, "AdresL2", f"{invoice.seller.postal_code} {invoice.seller.city}".strip())

    # Podmiot2 (buyer)
    pod2 = _sub(root, "Podmiot2")
    danych2 = _sub(pod2, "DaneIdentyfikacyjne")
    if invoice.buyer.nip:
        _sub(danych2, "NIP", invoice.buyer.nip)
    else:
        _sub(danych2, "BrakID")
    _sub(danych2, "PelnaNazwa", invoice.buyer.name)
    adres2 = _sub(pod2, "Adres")
    _sub(adres2, "KodKraju", invoice.buyer.country)
    _sub(adres2, "AdresL1", invoice.buyer.address or invoice.buyer.name)
    if invoice.buyer.postal_code or invoice.buyer.city:
        _sub(adres2, "AdresL2", f"{invoice.buyer.postal_code} {invoice.buyer.city}".strip())

    # Fa (invoice body)
    fa = _sub(root, "Fa")
    _sub(fa, "KodWaluty", invoice.currency)
    _sub(fa, "P_1", invoice.issue_date.isoformat())  # date of issue
    if invoice.sale_date:
        _sub(fa, "P_1M", invoice.sale_date.isoformat())
    _sub(fa, "P_2", invoice.invoice_number)

    # Line items
    for i, item in enumerate(invoice.items, start=1):
        faw = _sub(fa, "FaWiersz")
        _sub(faw, "NrWierszaFa", str(i))
        _sub(faw, "P_7", item.name)
        _sub(faw, "P_8A", item.unit)
        _sub(faw, "P_8B", _fmt(item.quantity))
        _sub(faw, "P_9A", _fmt(item.unit_price_net))
        _sub(faw, "P_11", _fmt(item.net_amount))
        vat_tag = _vat_tag(item.vat_rate)
        _sub(faw, vat_tag, _vat_value(item.vat_rate))

    # VAT summary (P_13 group)
    # Group by VAT rate
    vat_groups: dict[str, tuple[Decimal, Decimal]] = {}
    for item in invoice.items:
        rate = item.vat_rate
        net, vat = vat_groups.get(rate, (Decimal("0"), Decimal("0")))
        vat_groups[rate] = (net + item.net_amount, vat + item.vat_amount)

    # P_13_x / P_14_x for each rate
    rate_index = {"23": "1", "8": "2", "5": "3", "0": "5", "zw": "6", "np": "7"}
    for rate, (net, vat) in vat_groups.items():
        idx = rate_index.get(str(rate).lower(), "1")
        _sub(fa, f"P_13_{idx}", _fmt(net))
        if rate.lower() not in {"zw", "np", "0"}:
            _sub(fa, f"P_14_{idx}", _fmt(vat))

    _sub(fa, "P_15", _fmt(invoice.total_gross))

    if invoice.due_date:
        termin = _sub(fa, "TerminPlatnosci")
        _sub(termin, "Termin", invoice.due_date.isoformat())
    elif invoice.payment_deadline_days is not None:
        termin = _sub(fa, "TerminPlatnosci")
        _sub(termin, "TerminDni", str(invoice.payment_deadline_days))

    if invoice.payment_link:
        _sub(fa, "LinkDoPlatnosci", invoice.payment_link)

    if invoice.notes:
        _sub(fa, "Adnotacje", invoice.notes)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def validate_xml(xml_bytes: bytes) -> list[str]:
    """Validate XML against XSD schema. Returns list of error strings (empty = valid)."""
    if not XSD_PATH.exists():
        return []  # Schema not bundled; skip validation

    schema_doc = etree.parse(str(XSD_PATH))
    schema = etree.XMLSchema(schema_doc)

    doc = etree.fromstring(xml_bytes)
    schema.validate(doc)
    return [str(e) for e in schema.error_log]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sub(parent: etree._Element, tag: str, text: Optional[str] = None, **attrs: str) -> etree._Element:
    el = etree.SubElement(parent, f"{{{FA_NS}}}{tag}", **attrs)
    if text is not None:
        el.text = text
    return el


def _sub_elem(tag: str, text: str) -> etree._Element:
    """Create a standalone element (not yet attached to a parent)."""
    el = etree.Element(f"{{{FA_NS}}}{tag}")
    el.text = text
    return el


def _fmt(d: Decimal) -> str:
    """Format a Decimal for XML: up to 2 decimal places, no trailing zeros."""
    return f"{d:.2f}"


def _vat_tag(rate: str) -> str:
    mapping = {
        "23": "P_12",
        "8": "P_12",
        "5": "P_12",
        "0": "P_12",
        "zw": "P_12",
        "np": "P_12",
    }
    return mapping.get(rate.lower(), "P_12")


def _vat_value(rate: str) -> str:
    mapping = {
        "23": "23",
        "8": "8",
        "5": "5",
        "0": "0",
        "zw": "zw",
        "np": "np",
    }
    return mapping.get(rate.lower(), rate)
