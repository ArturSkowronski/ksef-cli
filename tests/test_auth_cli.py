"""CLI tests for ksef auth commands with --json flag."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from typer.testing import CliRunner

from ksef.main import app

runner = CliRunner()


def _future_expiry(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _past_expiry() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def test_auth_status_json_active_session():
    """--json outputs valid JSON with sessionActive=true when token is valid."""
    cfg = {
        "nip": "1234567890",
        "environment": "PRD",
        "session_token": "tok_abc123xyz",
        "session_expiry": _future_expiry(1),
        "refresh_token": "ref_abc",
        "refresh_expiry": _future_expiry(24),
    }
    with patch("ksef.auth.config.load", return_value=cfg):
        result = runner.invoke(app, ["auth", "status", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["nip"] == "1234567890"
    assert data["environment"] == "PRD"
    assert data["sessionActive"] is True
    assert data["expiresIn"] > 0
    assert "expiry" in data


def test_auth_status_json_expired_session():
    """--json outputs sessionActive=false when token is expired."""
    cfg = {
        "nip": "1234567890",
        "environment": "PRD",
        "session_token": "tok_expired",
        "session_expiry": _past_expiry(),
        "refresh_token": "",
        "refresh_expiry": "",
    }
    with patch("ksef.auth.config.load", return_value=cfg):
        result = runner.invoke(app, ["auth", "status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["sessionActive"] is False
    assert data["expiresIn"] == 0


def test_auth_status_json_no_token():
    """--json outputs sessionActive=false when no token stored."""
    cfg = {
        "nip": "1234567890",
        "environment": "PRD",
        "session_token": "",
        "session_expiry": "",
        "refresh_token": "",
        "refresh_expiry": "",
    }
    with patch("ksef.auth.config.load", return_value=cfg):
        result = runner.invoke(app, ["auth", "status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["sessionActive"] is False
    assert data["expiresIn"] == 0


def test_auth_status_no_json_unchanged():
    """Without --json, output is NOT valid JSON (Rich table, human-readable)."""
    cfg = {
        "nip": "1234567890",
        "environment": "PRD",
        "session_token": "",
        "session_expiry": "",
        "refresh_token": "",
        "refresh_expiry": "",
    }
    with patch("ksef.auth.config.load", return_value=cfg):
        result = runner.invoke(app, ["auth", "status"])

    assert result.exit_code == 0
    # Without --json the output is Rich markup, not pure JSON
    try:
        json.loads(result.output)
        assert False, "Expected non-JSON output without --json flag"
    except (json.JSONDecodeError, ValueError):
        pass  # expected
