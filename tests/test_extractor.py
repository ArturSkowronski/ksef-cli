"""Tests for ksef.extractor — heuristic parsing."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ksef.extractor import _dec, _find_invoice_number, _find_nips, _heuristic_parse


SAMPLE_TEXT = """
FAKTURA VAT NR FV/2024/007

Data wystawienia: 2024-03-15

Sprzedawca:
ABC Sp. z o.o.
NIP: 1234567890
ul. Sprzedawcza 10, 00-100 Warszawa

Nabywca:
XYZ S.A.
NIP: 9876543210
ul. Kupiecka 5, 30-001 Kraków

Lp. Nazwa                  Ilość  J.m.  Cena netto  VAT%  Wartość netto  VAT    Brutto
1   Usługa programistyczna 8      godz  100,00      23%   800,00         184,00 984,00

Razem do zapłaty: 984,00 PLN
"""


def test_find_invoice_number():
    num = _find_invoice_number(SAMPLE_TEXT)
    assert "FV/2024/007" in num or "FV" in num


def test_find_nips():
    nips = _find_nips(SAMPLE_TEXT)
    assert "1234567890" in nips
    assert "9876543210" in nips


def test_dec_comma():
    assert _dec("800,00") == Decimal("800.00")


def test_dec_dot():
    assert _dec("800.00") == Decimal("800.00")


def test_heuristic_parse_returns_invoice_data():
    data, confidence = _heuristic_parse(SAMPLE_TEXT)
    assert data.invoice_number != ""
    assert data.issue_date is not None
    assert data.seller.nip == "1234567890"
    assert confidence > 0


def test_heuristic_parse_low_confidence_for_empty():
    data, confidence = _heuristic_parse("")
    assert confidence == 0.0


def test_heuristic_parse_date():
    data, _ = _heuristic_parse(SAMPLE_TEXT)
    assert data.issue_date.year == 2024
    assert data.issue_date.month == 3
    assert data.issue_date.day == 15
