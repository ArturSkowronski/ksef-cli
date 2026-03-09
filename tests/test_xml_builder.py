"""Tests for ksef.xml_builder (FA(3))."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from lxml import etree

from ksef.models import BuyerData, InvoiceData, LineItem, SellerData
from ksef.xml_builder import FA_NS, build_xml, validate_xml


def _sample_invoice() -> InvoiceData:
    return InvoiceData(
        invoice_number="FV/2024/001",
        issue_date=date(2024, 1, 15),
        seller=SellerData(
            nip="1234567890",
            name="Sprzedawca Sp. z o.o.",
            address="ul. Testowa 1",
            postal_code="00-001",
            city="Warszawa",
        ),
        buyer=BuyerData(
            nip="9876543210",
            name="Nabywca S.A.",
            address="ul. Kupiecka 5",
            postal_code="30-001",
            city="Kraków",
        ),
        items=[
            LineItem(
                name="Usługa programistyczna",
                unit="godz",
                quantity=Decimal("8"),
                unit_price_net=Decimal("100.00"),
                vat_rate="23",
                net_amount=Decimal("800.00"),
                vat_amount=Decimal("184.00"),
                gross_amount=Decimal("984.00"),
            )
        ],
        total_net=Decimal("800.00"),
        total_vat=Decimal("184.00"),
        total_gross=Decimal("984.00"),
    )


def test_build_xml_returns_bytes():
    xml = build_xml(_sample_invoice())
    assert isinstance(xml, bytes)
    assert b"<?xml" in xml


def test_xml_parses():
    xml = build_xml(_sample_invoice())
    root = etree.fromstring(xml)
    assert root.tag == f"{{{FA_NS}}}Faktura"


def test_xml_fa3_namespace():
    """FA(3) namespace should be the new 2025 one."""
    assert "2025/06/25/13775" in FA_NS


def test_xml_fa3_header():
    """Header should reference FA (3) and WariantFormularza=3."""
    xml = build_xml(_sample_invoice())
    root = etree.fromstring(xml)
    kod = root.find(f".//{{{FA_NS}}}KodFormularza")
    assert kod is not None
    assert kod.get("kodSystemowy") == "FA (3)"
    wariant = root.find(f".//{{{FA_NS}}}WariantFormularza")
    assert wariant is not None
    assert wariant.text == "3"


def test_xml_contains_invoice_number():
    xml = build_xml(_sample_invoice())
    root = etree.fromstring(xml)
    p2 = root.find(f".//{{{FA_NS}}}P_2")
    assert p2 is not None
    assert p2.text == "FV/2024/001"


def test_xml_contains_seller_nip():
    xml = build_xml(_sample_invoice())
    root = etree.fromstring(xml)
    nips = root.findall(f".//{{{FA_NS}}}NIP")
    assert len(nips) >= 1
    assert nips[0].text == "1234567890"


def test_xml_contains_line_item():
    xml = build_xml(_sample_invoice())
    root = etree.fromstring(xml)
    rows = root.findall(f".//{{{FA_NS}}}FaWiersz")
    assert len(rows) == 1
    p7 = rows[0].find(f"{{{FA_NS}}}P_7")
    assert p7 is not None
    assert p7.text == "Usługa programistyczna"


def test_xml_total_gross():
    xml = build_xml(_sample_invoice())
    root = etree.fromstring(xml)
    p15 = root.find(f".//{{{FA_NS}}}P_15")
    assert p15 is not None
    assert p15.text == "984.00"


def test_validate_xml_no_schema():
    """validate_xml should return empty list when schema file is absent."""
    xml = build_xml(_sample_invoice())
    errors = validate_xml(xml)
    assert isinstance(errors, list)


def test_buyer_without_nip():
    invoice = _sample_invoice()
    invoice.buyer.nip = None
    xml = build_xml(invoice)
    root = etree.fromstring(xml)
    brak = root.find(f".//{{{FA_NS}}}BrakID")
    assert brak is not None


def test_payment_link():
    """FA(3) LinkDoPlatnosci should appear in XML."""
    invoice = _sample_invoice()
    invoice.payment_link = "https://pay.example.com/inv/123"
    xml = build_xml(invoice)
    root = etree.fromstring(xml)
    link = root.find(f".//{{{FA_NS}}}LinkDoPlatnosci")
    assert link is not None
    assert link.text == "https://pay.example.com/inv/123"


def test_payment_deadline_days():
    """FA(3) payment_deadline_days should render TerminDni."""
    invoice = _sample_invoice()
    invoice.payment_deadline_days = 14
    xml = build_xml(invoice)
    root = etree.fromstring(xml)
    termin_dni = root.find(f".//{{{FA_NS}}}TerminDni")
    assert termin_dni is not None
    assert termin_dni.text == "14"
