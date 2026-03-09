"""Tests for ksef.invoice — helpers and session workflow."""

from __future__ import annotations

from pathlib import Path

import pytest

from ksef.invoice import _to_xml


def test_to_xml_passthrough_xml(tmp_path: Path):
    """XML files are returned as-is."""
    xml_content = b"<?xml version='1.0'?><root/>"
    xml_file = tmp_path / "test.xml"
    xml_file.write_bytes(xml_content)
    result = _to_xml(xml_file)
    assert result == xml_content


def test_to_xml_unsupported_extension(tmp_path: Path):
    """Unsupported file types should raise (typer.Exit or SystemExit)."""
    import click

    bad_file = tmp_path / "test.docx"
    bad_file.write_bytes(b"fake content")
    with pytest.raises((SystemExit, click.exceptions.Exit)):
        _to_xml(bad_file)
