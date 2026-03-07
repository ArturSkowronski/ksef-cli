"""Tests for ksef.client."""

from __future__ import annotations

import httpx
import pytest
import respx

from ksef.client import KSeFClient, KSeFError, _parse_error


@respx.mock
def test_authorisation_challenge_success():
    respx.post("https://ksef.mf.gov.pl/api/online/Session/AuthorisationChallenge").mock(
        return_value=httpx.Response(
            200,
            json={"challenge": "abc123", "timestamp": "2024-01-01T00:00:00Z"},
        )
    )
    with KSeFClient() as client:
        result = client.authorisation_challenge("1234567890")
    assert result["challenge"] == "abc123"


@respx.mock
def test_ksef_error_parsing():
    respx.post("https://ksef.mf.gov.pl/api/online/Session/AuthorisationChallenge").mock(
        return_value=httpx.Response(
            400,
            json={
                "exceptionDetailList": [
                    {
                        "exceptionCode": 21201,
                        "exceptionDescription": "Nieprawidłowy NIP",
                    }
                ]
            },
        )
    )
    with KSeFClient() as client:
        with pytest.raises(KSeFError) as exc_info:
            client.authorisation_challenge("bad-nip")
    assert "21201" in str(exc_info.value)


@respx.mock
def test_network_error_retry():
    """Client should retry once on connection error then raise KSeFError."""
    respx.post("https://ksef.mf.gov.pl/api/online/Session/AuthorisationChallenge").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    with KSeFClient() as client:
        with pytest.raises(KSeFError) as exc_info:
            client.authorisation_challenge("1234567890")
    assert exc_info.value.code == "NETWORK_ERROR"


@respx.mock
def test_session_token_injected():
    """SessionToken header should be present when client has a session token."""
    route = respx.get("https://ksef.mf.gov.pl/api/online/Session/Terminate").mock(
        return_value=httpx.Response(200, json={"sessionToken": None})
    )
    with KSeFClient(session_token="my-token-123") as client:
        client.terminate_session()
    assert route.called
    assert route.calls[0].request.headers.get("sessiontoken") == "my-token-123"
