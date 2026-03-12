"""CLI tests for ksef invoice commands with --json flag."""
from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from ksef.main import app

runner = CliRunner()

_FAKE_INVOICE = {
    "ksefNumber": "KSeF/100/2024",
    "invoiceNumber": "FV/1/2024",
    "issueDate": "2024-01-15",
    "buyer": {"name": "Kupujący Sp. z o.o."},
    "seller": {"name": "Sprzedający SA"},
    "netAmount": "1000.00",
    "grossAmount": "1230.00",
    "currency": "PLN",
}


def test_invoice_list_json_returns_invoices():
    """--json outputs {"invoices": [...]} with flat buyer/seller strings."""
    mock_result = {"invoices": [_FAKE_INVOICE], "hasMore": False}

    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient:
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.query_invoice_metadata.return_value = mock_result

        result = runner.invoke(app, ["invoice", "list", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "invoices" in data
    inv = data["invoices"][0]
    assert inv["ksefNumber"] == "KSeF/100/2024"
    assert inv["invoiceNumber"] == "FV/1/2024"
    assert inv["buyer"] == "Kupujący Sp. z o.o."   # flat string, not dict
    assert inv["seller"] == "Sprzedający SA"
    assert inv["netAmount"] == "1000.00"
    assert inv["currency"] == "PLN"


def test_invoice_list_json_empty():
    """--json outputs {"invoices": []} when no invoices found."""
    mock_result = {"invoices": [], "hasMore": False}

    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient:
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.query_invoice_metadata.return_value = mock_result

        result = runner.invoke(app, ["invoice", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {"invoices": []}


def test_invoice_list_no_json_unchanged():
    """Without --json, output is NOT valid JSON (Rich table)."""
    mock_result = {"invoices": [_FAKE_INVOICE], "hasMore": False}

    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient:
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.query_invoice_metadata.return_value = mock_result

        result = runner.invoke(app, ["invoice", "list"])

    assert result.exit_code == 0
    try:
        json.loads(result.output)
        assert False, "Expected non-JSON output without --json"
    except (json.JSONDecodeError, ValueError):
        pass
