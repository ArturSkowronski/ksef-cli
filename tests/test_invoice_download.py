"""CLI tests for `ksef invoice download` — batch download + PDF generation."""
from __future__ import annotations

import calendar
import json
from datetime import date
from unittest.mock import patch

from typer.testing import CliRunner

from ksef.client import KSeFError
from ksef.main import app

runner = CliRunner()

_INVOICE_A = {
    "ksefNumber": "6751577855-20260506-6A88E4A-B0",
    "invoiceNumber": "FV/1/2026",
    "issueDate": "2026-05-06",
}
_INVOICE_B = {
    "ksefNumber": "6751577855-20260512-0B00C0D-3F",
    "invoiceNumber": "FV/2/2026",
    "issueDate": "2026-05-12",
}

_FAKE_XML = b"<?xml version='1.0'?><Faktura/>"
_FAKE_PDF = b"%PDF-1.4 fake"


def _invoke(args, query_results, xml_by_ksef=None, render=None):
    """Run `invoice download` with mocked session, client, and PDF renderer.

    query_results: list of metadata-query responses (one per query call).
    xml_by_ksef: dict ksef_number -> bytes, or callable; defaults to _FAKE_XML.
    """
    def _get_invoice(ksef_number):
        if callable(xml_by_ksef):
            return xml_by_ksef(ksef_number)
        if xml_by_ksef is not None:
            return xml_by_ksef[ksef_number]
        return _FAKE_XML

    with patch("ksef.invoice.config.require_session", return_value="sess_tok"), \
         patch("ksef.invoice.KSeFClient") as MockClient, \
         patch("ksef.pdf_renderer.render_invoice_pdf",
               side_effect=render or (lambda xml: _FAKE_PDF)) as mock_render:
        mock_inst = MockClient.return_value.__enter__.return_value
        mock_inst.query_invoice_metadata.side_effect = query_results
        mock_inst.get_invoice_by_ksef.side_effect = _get_invoice

        result = runner.invoke(app, ["invoice", "download", *args])

    return result, mock_inst, mock_render


def test_download_default_range_is_previous_month(tmp_path):
    """No options → queries the previous calendar month and writes PDFs."""
    result, mock_inst, _ = _invoke(
        ["--out-dir", str(tmp_path)],
        query_results=[{"invoices": [_INVOICE_A], "hasMore": False}],
    )

    assert result.exit_code == 0, result.output

    today = date.today()
    prev_last = today.replace(day=1)
    year = prev_last.year if prev_last.month > 1 else prev_last.year - 1
    month = prev_last.month - 1 or 12
    last_day = calendar.monthrange(year, month)[1]

    payload = mock_inst.query_invoice_metadata.call_args[0][0]
    assert payload["dateRange"]["from"] == f"{year:04d}-{month:02d}-01T00:00:00.000Z"
    assert payload["dateRange"]["to"] == f"{year:04d}-{month:02d}-{last_day:02d}T23:59:59.999Z"
    assert payload["subjectType"] == "subject1"

    assert (tmp_path / f"{_INVOICE_A['ksefNumber']}.pdf").read_bytes() == _FAKE_PDF


def test_download_explicit_month(tmp_path):
    """--month 2026-04 → full April range in payload."""
    result, mock_inst, _ = _invoke(
        ["--month", "2026-04", "--out-dir", str(tmp_path)],
        query_results=[{"invoices": [_INVOICE_A], "hasMore": False}],
    )

    assert result.exit_code == 0, result.output
    payload = mock_inst.query_invoice_metadata.call_args[0][0]
    assert payload["dateRange"]["from"] == "2026-04-01T00:00:00.000Z"
    assert payload["dateRange"]["to"] == "2026-04-30T23:59:59.999Z"


def test_download_json_summary(tmp_path):
    """--json emits outDir, downloaded files, and empty failed list."""
    result, _, _ = _invoke(
        ["--month", "2026-05", "--out-dir", str(tmp_path), "--json"],
        query_results=[{"invoices": [_INVOICE_A, _INVOICE_B], "hasMore": False}],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["outDir"] == str(tmp_path)
    assert data["failed"] == []
    assert len(data["downloaded"]) == 2
    assert data["downloaded"][0]["ksefNumber"] == _INVOICE_A["ksefNumber"]
    assert data["downloaded"][0]["files"] == [
        str(tmp_path / f"{_INVOICE_A['ksefNumber']}.pdf")
    ]


def test_download_partial_failure_continues(tmp_path):
    """One invoice fails to download → others still saved, exit 0, failure reported."""
    def _get(ksef_number):
        if ksef_number == _INVOICE_A["ksefNumber"]:
            raise KSeFError("500", "boom")
        return _FAKE_XML

    result, _, _ = _invoke(
        ["--month", "2026-05", "--out-dir", str(tmp_path), "--json"],
        query_results=[{"invoices": [_INVOICE_A, _INVOICE_B], "hasMore": False}],
        xml_by_ksef=_get,
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data["downloaded"]) == 1
    assert data["downloaded"][0]["ksefNumber"] == _INVOICE_B["ksefNumber"]
    assert len(data["failed"]) == 1
    assert data["failed"][0]["ksefNumber"] == _INVOICE_A["ksefNumber"]
    assert "boom" in data["failed"][0]["error"]
    assert (tmp_path / f"{_INVOICE_B['ksefNumber']}.pdf").exists()
    assert not (tmp_path / f"{_INVOICE_A['ksefNumber']}.pdf").exists()


def test_download_all_invoices_failed_exits_1(tmp_path):
    """Every invoice fails → exit code 1."""
    def _get(ksef_number):
        raise KSeFError("500", "boom")

    result, _, _ = _invoke(
        ["--month", "2026-05", "--out-dir", str(tmp_path)],
        query_results=[{"invoices": [_INVOICE_A], "hasMore": False}],
        xml_by_ksef=_get,
    )

    assert result.exit_code == 1


def test_download_format_xml_skips_renderer(tmp_path):
    """--format xml writes .xml files and never calls the PDF renderer."""
    result, _, mock_render = _invoke(
        ["--month", "2026-05", "--out-dir", str(tmp_path), "--format", "xml"],
        query_results=[{"invoices": [_INVOICE_A], "hasMore": False}],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / f"{_INVOICE_A['ksefNumber']}.xml").read_bytes() == _FAKE_XML
    assert not (tmp_path / f"{_INVOICE_A['ksefNumber']}.pdf").exists()
    mock_render.assert_not_called()


def test_download_format_both_writes_xml_and_pdf(tmp_path):
    result, _, _ = _invoke(
        ["--month", "2026-05", "--out-dir", str(tmp_path), "--format", "both"],
        query_results=[{"invoices": [_INVOICE_A], "hasMore": False}],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / f"{_INVOICE_A['ksefNumber']}.xml").exists()
    assert (tmp_path / f"{_INVOICE_A['ksefNumber']}.pdf").exists()


def test_download_filename_sanitised(tmp_path):
    """Path-hostile characters in KSeF number are replaced in the filename."""
    weird = {"ksefNumber": "KSeF/100/2024", "invoiceNumber": "FV/1", "issueDate": "2026-05-01"}
    result, _, _ = _invoke(
        ["--month", "2026-05", "--out-dir", str(tmp_path)],
        query_results=[{"invoices": [weird], "hasMore": False}],
        xml_by_ksef=lambda k: _FAKE_XML,
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "KSeF_100_2024.pdf").exists()


def test_download_all_subjects_dedupes(tmp_path):
    """--all queries subject1 and subject2 and dedupes by KSeF number."""
    result, mock_inst, _ = _invoke(
        ["--month", "2026-05", "--out-dir", str(tmp_path), "--all", "--json"],
        query_results=[
            {"invoices": [_INVOICE_A], "hasMore": False},
            {"invoices": [_INVOICE_A, _INVOICE_B], "hasMore": False},
        ],
    )

    assert result.exit_code == 0, result.output
    subjects = [c.args[0]["subjectType"] for c in mock_inst.query_invoice_metadata.call_args_list]
    assert subjects == ["subject1", "subject2"]
    data = json.loads(result.output)
    assert len(data["downloaded"]) == 2  # _INVOICE_A only once


def test_download_no_invoices(tmp_path):
    """Empty result → friendly message, exit 0, no files."""
    result, _, _ = _invoke(
        ["--month", "2026-05", "--out-dir", str(tmp_path)],
        query_results=[{"invoices": [], "hasMore": False}],
    )

    assert result.exit_code == 0, result.output
    assert list(tmp_path.iterdir()) == []


def test_download_invalid_month_rejected(tmp_path):
    result, _, _ = _invoke(
        ["--month", "not-a-month", "--out-dir", str(tmp_path)],
        query_results=[],
    )
    assert result.exit_code != 0
