"""httpx-based KSeF API client with session management and error parsing."""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx
from rich.console import Console

from . import config

TIMEOUT = 30.0
API_PREFIX = "/api/v2"

_err_console = Console(stderr=True)


class KSeFError(Exception):
    """Raised on KSeF API errors with parsed code + message."""

    def __init__(self, code: str, message: str, status: int = 0) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(f"[{code}] {message}")


def _parse_error(response: httpx.Response) -> KSeFError:
    """Parse error from response — supports problem+json, nested exception, and legacy formats."""
    try:
        ct = response.headers.get("content-type", "")
        body = response.json()

        if "application/problem+json" in ct or "reasonCode" in body:
            # problem+json format
            code = body.get("reasonCode") or body.get("status") or str(response.status_code)
            msg = body.get("detail") or body.get("title") or response.text
        elif "exception" in body:
            # Nested exception format: {"exception": {"exceptionDetailList": [...]}}
            exc = body["exception"]
            details = exc.get("exceptionDetailList", [{}])
            first = details[0] if details else {}
            code = first.get("exceptionCode", str(response.status_code))
            desc = first.get("exceptionDescription", "")
            extra = first.get("details", [])
            msg = f"{desc} {'; '.join(extra)}".strip() if extra else desc or response.text
        else:
            # Legacy flat format
            code = (
                body.get("code", "")
                or body.get("exceptionDetailList", [{}])[0].get("exceptionCode", "")
                or str(response.status_code)
            )
            msg = (
                body.get("message", "")
                or body.get("exceptionDetailList", [{}])[0].get("exceptionDescription", "")
                or response.text
            )
    except Exception:
        code = str(response.status_code)
        msg = response.text or "Unknown error"
    return KSeFError(code=str(code), message=msg, status=response.status_code)


class KSeFClient:
    """Thin httpx wrapper around the KSeF REST API."""

    def __init__(
        self,
        access_token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = TIMEOUT,
    ) -> None:
        if base_url is None:
            base_url = config.get_base_url()

        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        self._client = httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: Optional[dict] = None,
        content_type: Optional[str] = None,
        raw_body: Optional[bytes] = None,
    ) -> httpx.Response:
        """Send a request with retry on network error, 429 backoff, and KSeFError on 4xx/5xx."""
        kwargs: dict[str, Any] = {}
        if json_body is not None:
            kwargs["json"] = json_body
        if raw_body is not None:
            kwargs["content"] = raw_body
            if content_type:
                kwargs["headers"] = {"Content-Type": content_type}
        if params:
            kwargs["params"] = params

        for attempt in range(2):
            try:
                resp = self._client.request(method, path, **kwargs)
                break
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                if attempt == 1:
                    raise KSeFError(
                        "NETWORK_ERROR",
                        f"Network error: {exc}",
                    ) from exc

        # Handle 429 Too Many Requests with Retry-After
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "5")
            try:
                wait = int(retry_after)
            except ValueError:
                wait = 5
            time.sleep(min(wait, 60))
            # One retry after rate limit
            resp = self._client.request(method, path, **kwargs)

        if resp.is_error:
            raise _parse_error(resp)
        return resp

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self._request("POST", path, **kwargs)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "KSeFClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Auth endpoints
    # ------------------------------------------------------------------

    def get_public_key(self) -> list | dict:
        """GET /api/v2/security/public-key-certificates"""
        resp = self.get(f"{API_PREFIX}/security/public-key-certificates")
        return resp.json()

    def auth_challenge(self, nip: str) -> dict:
        """POST /api/v2/auth/challenge"""
        resp = self.post(
            f"{API_PREFIX}/auth/challenge",
            json_body={"contextIdentifier": {"type": "nip", "value": nip}},
        )
        return resp.json()

    def auth_ksef_token(self, payload: dict) -> dict:
        """POST /api/v2/auth/ksef-token"""
        resp = self.post(f"{API_PREFIX}/auth/ksef-token", json_body=payload)
        return resp.json()

    def auth_token_status(self, reference_number: str) -> dict:
        """GET /api/v2/auth/token/status/{ref}"""
        resp = self.get(f"{API_PREFIX}/auth/token/status/{reference_number}")
        return resp.json()

    def auth_token_redeem(self, authentication_token: str) -> dict:
        """POST /api/v2/auth/token/redeem — requires Bearer auth header."""
        resp = self._client.request(
            "POST",
            f"{API_PREFIX}/auth/token/redeem",
            headers={
                "Authorization": f"Bearer {authentication_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={"authenticationToken": authentication_token},
        )
        if resp.is_error:
            raise _parse_error(resp)
        return resp.json()

    def auth_token_refresh(self, refresh_token: str) -> dict:
        """POST /api/v2/auth/token/refresh — refresh access token using refresh token."""
        resp = self._client.request(
            "POST",
            f"{API_PREFIX}/auth/token/refresh",
            headers={
                "Authorization": f"Bearer {refresh_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={},
        )
        if resp.is_error:
            raise _parse_error(resp)
        return resp.json()

    # ------------------------------------------------------------------
    # Session endpoints (session-based invoice workflow)
    # ------------------------------------------------------------------

    def open_session(self, form_code: dict, encryption: dict) -> dict:
        """POST /api/v2/sessions/online — open an invoice sending session."""
        resp = self.post(
            f"{API_PREFIX}/sessions/online",
            json_body={"formCode": form_code, "encryption": encryption},
        )
        return resp.json()

    def send_invoice_in_session(self, session_ref: str, payload: dict) -> dict:
        """POST /api/v2/sessions/online/{sessionRef}/invoices/"""
        resp = self.post(
            f"{API_PREFIX}/sessions/online/{session_ref}/invoices/",
            json_body=payload,
        )
        return resp.json()

    def close_session(self, session_ref: str) -> dict:
        """POST /api/v2/sessions/online/{sessionRef}/close"""
        resp = self.post(f"{API_PREFIX}/sessions/online/{session_ref}/close", json_body={})
        return resp.json()

    def session_status(self, session_ref: str) -> dict:
        """GET /api/v2/sessions/{sessionRef}"""
        resp = self.get(f"{API_PREFIX}/sessions/{session_ref}")
        return resp.json()

    def invoice_status_in_session(self, session_ref: str, invoice_ref: str) -> dict:
        """GET /api/v2/sessions/{sessionRef}/invoices/{invoiceRef}"""
        resp = self.get(f"{API_PREFIX}/sessions/{session_ref}/invoices/{invoice_ref}")
        return resp.json()

    # ------------------------------------------------------------------
    # Invoice endpoints
    # ------------------------------------------------------------------

    def get_invoice_by_ksef(self, ksef_number: str) -> bytes:
        """GET /api/v2/invoices/ksef/{ksefNumber}"""
        resp = self.get(f"{API_PREFIX}/invoices/ksef/{ksef_number}")
        return resp.content

    def query_invoice_metadata(self, payload: dict) -> dict:
        """POST /api/v2/invoices/query/metadata — synchronous query with pagination."""
        resp = self.post(f"{API_PREFIX}/invoices/query/metadata", json_body=payload)
        result = resp.json()
        # Capture continuation token from header for pagination
        continuation = resp.headers.get("x-continuation-token")
        if continuation:
            result["_continuationToken"] = continuation
        return result

