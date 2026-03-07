"""Tests for ksef.client (v2 API)."""

from __future__ import annotations

import httpx
import pytest
import respx

from ksef.client import KSeFClient, KSeFError


@respx.mock
def test_auth_challenge_success():
    respx.post("https://ksef.mf.gov.pl/api/v2/auth/challenge").mock(
        return_value=httpx.Response(
            200,
            json={"challenge": "abc123", "timestamp": 1700000000000},
        )
    )
    with KSeFClient() as client:
        result = client.auth_challenge("1234567890")
    assert result["challenge"] == "abc123"


@respx.mock
def test_ksef_error_parsing():
    respx.post("https://ksef.mf.gov.pl/api/v2/auth/challenge").mock(
        return_value=httpx.Response(
            400,
            json={"code": 21201, "message": "Nieprawidłowy NIP"},
        )
    )
    with KSeFClient() as client:
        with pytest.raises(KSeFError) as exc_info:
            client.auth_challenge("bad-nip")
    assert "21201" in str(exc_info.value)


@respx.mock
def test_network_error_retry():
    respx.post("https://ksef.mf.gov.pl/api/v2/auth/challenge").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    with KSeFClient() as client:
        with pytest.raises(KSeFError) as exc_info:
            client.auth_challenge("1234567890")
    assert exc_info.value.code == "NETWORK_ERROR"


@respx.mock
def test_access_token_injected():
    route = respx.post("https://ksef.mf.gov.pl/api/v2/auth/logout").mock(
        return_value=httpx.Response(200, json={})
    )
    with KSeFClient(access_token="my-token-123") as client:
        client.auth_logout()
    assert route.called
    assert route.calls[0].request.headers.get("authorization") == "Bearer my-token-123"
