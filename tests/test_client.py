"""Tests for ksef.client (KSeF API)."""

from __future__ import annotations

import httpx
import pytest
import respx

from ksef.client import KSeFClient, KSeFError

BASE = "https://api.ksef.mf.gov.pl"
PFX = "/api/v2"


@respx.mock
def test_auth_challenge_success():
    respx.post(f"{BASE}{PFX}/auth/challenge").mock(
        return_value=httpx.Response(
            200,
            json={"challenge": "abc123", "timestampMs": 1700000000000},
        )
    )
    with KSeFClient(base_url=BASE) as client:
        result = client.auth_challenge("1234567890")
    assert result["challenge"] == "abc123"


@respx.mock
def test_ksef_error_parsing_legacy():
    respx.post(f"{BASE}{PFX}/auth/challenge").mock(
        return_value=httpx.Response(
            400,
            json={"code": 21201, "message": "Nieprawidłowy NIP"},
        )
    )
    with KSeFClient(base_url=BASE) as client:
        with pytest.raises(KSeFError) as exc_info:
            client.auth_challenge("bad-nip")
    assert "21201" in str(exc_info.value)


@respx.mock
def test_nested_exception_error_parsing():
    """Real API wraps errors in {"exception": {"exceptionDetailList": [...]}}."""
    respx.post(f"{BASE}{PFX}/auth/ksef-token").mock(
        return_value=httpx.Response(
            400,
            json={
                "exception": {
                    "exceptionDetailList": [
                        {
                            "exceptionCode": 21405,
                            "exceptionDescription": "Błąd walidacji danych wejściowych.",
                            "details": ["'challenge' is not in the correct format."],
                        }
                    ],
                    "serviceCode": "00-abc-def-00",
                    "timestamp": "2026-03-08T08:54:19.960041Z",
                }
            },
        )
    )
    with KSeFClient(base_url=BASE) as client:
        with pytest.raises(KSeFError) as exc_info:
            client.auth_ksef_token({"challenge": "fake"})
    assert "21405" in str(exc_info.value)
    assert "challenge" in exc_info.value.message


@respx.mock
def test_problem_json_error_parsing():
    respx.post(f"{BASE}{PFX}/auth/challenge").mock(
        return_value=httpx.Response(
            422,
            json={
                "type": "urn:ksef:error:validation",
                "title": "Validation Error",
                "status": 422,
                "detail": "Invalid NIP format",
                "reasonCode": "INVALID_NIP",
            },
            headers={"content-type": "application/problem+json"},
        )
    )
    with KSeFClient(base_url=BASE) as client:
        with pytest.raises(KSeFError) as exc_info:
            client.auth_challenge("bad")
    assert exc_info.value.code == "INVALID_NIP"
    assert "Invalid NIP format" in exc_info.value.message


@respx.mock
def test_network_error_retry():
    respx.post(f"{BASE}{PFX}/auth/challenge").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    with KSeFClient(base_url=BASE) as client:
        with pytest.raises(KSeFError) as exc_info:
            client.auth_challenge("1234567890")
    assert exc_info.value.code == "NETWORK_ERROR"


@respx.mock
def test_access_token_injected():
    route = respx.post(f"{BASE}{PFX}/sessions/online").mock(
        return_value=httpx.Response(200, json={"referenceNumber": "sess-123"})
    )
    with KSeFClient(access_token="my-token-123", base_url=BASE) as client:
        client.open_session(
            form_code={"systemCode": "FA", "schemaVersion": "1-0E", "value": "106"},
            encryption={"encryptedSymmetricKey": "abc", "initializationVector": "def"},
        )
    assert route.called
    assert route.calls[0].request.headers.get("authorization") == "Bearer my-token-123"


@respx.mock
def test_open_session():
    respx.post(f"{BASE}{PFX}/sessions/online").mock(
        return_value=httpx.Response(200, json={"referenceNumber": "sess-abc"})
    )
    with KSeFClient(base_url=BASE) as client:
        result = client.open_session(
            form_code={"systemCode": "FA"},
            encryption={"encryptedSymmetricKey": "key", "initializationVector": "iv"},
        )
    assert result["referenceNumber"] == "sess-abc"


@respx.mock
def test_send_invoice_in_session():
    respx.post(f"{BASE}{PFX}/sessions/online/sess-123/invoices/").mock(
        return_value=httpx.Response(200, json={"referenceNumber": "inv-456"})
    )
    with KSeFClient(base_url=BASE) as client:
        result = client.send_invoice_in_session("sess-123", {"invoiceHash": {}})
    assert result["referenceNumber"] == "inv-456"


@respx.mock
def test_close_session():
    respx.post(f"{BASE}{PFX}/sessions/online/sess-123/close").mock(
        return_value=httpx.Response(200, json={"status": "closed"})
    )
    with KSeFClient(base_url=BASE) as client:
        result = client.close_session("sess-123")
    assert result["status"] == "closed"


@respx.mock
def test_query_invoice_metadata_with_continuation():
    respx.post(f"{BASE}{PFX}/invoices/query/metadata").mock(
        return_value=httpx.Response(
            200,
            json={"invoiceHeaderList": [{"ksefReferenceNumber": "K1"}]},
            headers={"x-continuation-token": "next-page-token"},
        )
    )
    with KSeFClient(base_url=BASE) as client:
        result = client.query_invoice_metadata({"queryCriteria": {}})
    assert result["_continuationToken"] == "next-page-token"
    assert len(result["invoiceHeaderList"]) == 1


@respx.mock
def test_get_invoice_by_ksef():
    respx.get(f"{BASE}{PFX}/invoices/ksef/1234567890-20240115-ABC").mock(
        return_value=httpx.Response(200, content=b"<Faktura/>")
    )
    with KSeFClient(base_url=BASE) as client:
        content = client.get_invoice_by_ksef("1234567890-20240115-ABC")
    assert content == b"<Faktura/>"


@respx.mock
def test_auth_token_status_path():
    respx.get(f"{BASE}{PFX}/auth/token/status/ref-123").mock(
        return_value=httpx.Response(
            200, json={"processingCode": 150, "processingDescription": "In progress"}
        )
    )
    with KSeFClient(base_url=BASE) as client:
        result = client.auth_token_status("ref-123")
    assert result["processingCode"] == 150


@respx.mock
def test_rate_limit_429(monkeypatch):
    """429 should trigger a retry after Retry-After."""
    monkeypatch.setattr("time.sleep", lambda _: None)
    call_count = 0

    def mock_side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={})
        return httpx.Response(200, json={"ok": True})

    respx.get(f"{BASE}{PFX}/security/public-key-certificates").mock(side_effect=mock_side_effect)
    with KSeFClient(base_url=BASE) as client:
        result = client.get_public_key()
    assert result.get("ok") is True
    assert call_count == 2
