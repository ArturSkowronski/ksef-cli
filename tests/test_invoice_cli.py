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

        result = runner.invoke(
            app,
            ["invoice", "list", "--json", "--date-from", "2024-01-01", "--date-to", "2024-01-31"],
        )

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


def test_invoice_list_queries_by_issue_date():
    """list must filter by the invoice issue date, not the KSeF registration date."""
    mock_result = {"invoices": [], "hasMore": False}

    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient:
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.query_invoice_metadata.return_value = mock_result

        result = runner.invoke(app, ["invoice", "list", "--json"])

    assert result.exit_code == 0, result.output
    payload = mock_inst.query_invoice_metadata.call_args[0][0]
    assert payload["dateRange"]["dateType"] == "issue"


def test_invoice_list_excludes_issue_date_outside_range():
    """An invoice whose issue date is outside the requested range is dropped."""
    out_of_range = {**_FAKE_INVOICE, "ksefNumber": "KSeF/999/2024", "issueDate": "2024-03-15"}
    mock_result = {"invoices": [_FAKE_INVOICE, out_of_range], "hasMore": False}

    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient:
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.query_invoice_metadata.return_value = mock_result

        result = runner.invoke(
            app,
            ["invoice", "list", "--json", "--date-from", "2024-01-01", "--date-to", "2024-01-31"],
        )

    assert result.exit_code == 0, result.output
    nums = [i["ksefNumber"] for i in json.loads(result.output)["invoices"]]
    assert "KSeF/100/2024" in nums
    assert "KSeF/999/2024" not in nums


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

        result = runner.invoke(
            app, ["invoice", "list", "--date-from", "2024-01-01", "--date-to", "2024-01-31"]
        )

    assert result.exit_code == 0
    try:
        json.loads(result.output)
        assert False, "Expected non-JSON output without --json"
    except (json.JSONDecodeError, ValueError):
        pass


def test_invoice_status_json():
    """--json outputs processingCode, ksefNumber."""
    mock_result = {
        "processingCode": 200,
        "processingDescription": "Processed successfully",
        "ksefNumber": "KSeF/200/2024",
    }
    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient:
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.session_status.return_value = mock_result

        result = runner.invoke(app, ["invoice", "status", "REF123", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["processingCode"] == 200
    assert data["ksefNumber"] == "KSeF/200/2024"
    assert data["processingDescription"] == "Processed successfully"


def test_invoice_status_json_missing_fields_are_null():
    """--json outputs null for missing optional fields."""
    mock_result = {"processingCode": 150, "processingDescription": "In progress"}
    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient:
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.session_status.return_value = mock_result

        result = runner.invoke(app, ["invoice", "status", "REF123", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["processingCode"] == 150
    assert data["ksefNumber"] is None


def test_invoice_send_json_with_wait(tmp_path):
    """--json after send+poll outputs invoiceRef, ksefNumber, processingCode."""
    xml_file = tmp_path / "inv.xml"
    xml_file.write_bytes(b"<?xml version='1.0'?><root/>")

    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient, \
         patch("ksef.invoice._to_xml", return_value=b"<xml/>"), \
         patch("ksef.invoice.validate_xml", return_value=[]), \
         patch("ksef.invoice.generate_session_keys", return_value=(b"k" * 32, b"i" * 16)), \
         patch("ksef.invoice.encrypt_aes_key", return_value="enckey=="), \
         patch("ksef.invoice.encrypt_invoice", return_value=b"encrypted"):
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.get_public_key.return_value = [{"usage": ["SymmetricKeyEncryption"], "publicKey": "---PEM---"}]
        mock_inst.open_session.return_value = {"referenceNumber": "SESS/1"}
        mock_inst.send_invoice_in_session.return_value = {"referenceNumber": "INV/1"}
        mock_inst.close_session.return_value = {}
        mock_inst.invoice_status_in_session.return_value = {
            "processingCode": 200,
            "ksefNumber": "KSeF/999/2024",
        }

        with patch("ksef.invoice._extract_public_key", return_value="---PEM---"):
            result = runner.invoke(app, ["invoice", "send", str(xml_file), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["invoiceRef"] == "INV/1"
    assert data["ksefNumber"] == "KSeF/999/2024"
    assert data["processingCode"] == 200


def test_invoice_send_json_no_wait(tmp_path):
    """--json --no-wait outputs invoiceRef with null ksefNumber/processingCode."""
    xml_file = tmp_path / "inv.xml"
    xml_file.write_bytes(b"<?xml version='1.0'?><root/>")

    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient, \
         patch("ksef.invoice._to_xml", return_value=b"<xml/>"), \
         patch("ksef.invoice.validate_xml", return_value=[]), \
         patch("ksef.invoice.generate_session_keys", return_value=(b"k" * 32, b"i" * 16)), \
         patch("ksef.invoice.encrypt_aes_key", return_value="enckey=="), \
         patch("ksef.invoice.encrypt_invoice", return_value=b"encrypted"):
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.get_public_key.return_value = []
        mock_inst.open_session.return_value = {"referenceNumber": "SESS/1"}
        mock_inst.send_invoice_in_session.return_value = {"referenceNumber": "INV/2"}
        mock_inst.close_session.return_value = {}

        with patch("ksef.invoice._extract_public_key", return_value="---PEM---"):
            result = runner.invoke(app, ["invoice", "send", str(xml_file), "--no-wait", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["invoiceRef"] == "INV/2"
    assert data["ksefNumber"] is None
    assert data["processingCode"] is None
