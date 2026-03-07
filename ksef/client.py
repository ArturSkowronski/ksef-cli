"""httpx-based KSeF API client with session management and error parsing."""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx
from rich.console import Console

KSEF_BASE_URL = "https://ksef.mf.gov.pl"
TIMEOUT = 30.0

_err_console = Console(stderr=True)


class KSeFError(Exception):
    """Raised on KSeF API errors with parsed code + message."""

    def __init__(self, code: str, message: str, status: int = 0) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(f"[{code}] {message}")


def _parse_error(response: httpx.Response) -> KSeFError:
    """Try to extract KSeF error code + message from a non-2xx response."""
    try:
        body = response.json()
        # KSeF wraps errors in various shapes; try common ones
        code = (
            body.get("exceptionDetailList", [{}])[0].get("exceptionCode", "")
            or body.get("code", "")
            or str(response.status_code)
        )
        msg = (
            body.get("exceptionDetailList", [{}])[0].get("exceptionDescription", "")
            or body.get("message", "")
            or response.text
        )
    except Exception:
        code = str(response.status_code)
        msg = response.text or "Unknown error"
    return KSeFError(code=code, message=msg, status=response.status_code)


class KSeFClient:
    """Thin httpx wrapper around the KSeF REST API."""

    def __init__(
        self,
        session_token: Optional[str] = None,
        base_url: str = KSEF_BASE_URL,
        timeout: float = TIMEOUT,
    ) -> None:
        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if session_token:
            headers["SessionToken"] = session_token

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
        """Send a request, retry once on network error, raise KSeFError on 4xx/5xx."""
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

    def authorisation_challenge(self, nip: str) -> dict:
        resp = self.post(
            "/api/online/Session/AuthorisationChallenge",
            json_body={"contextIdentifier": {"type": "onip", "identifier": nip}},
        )
        return resp.json()

    def init_token(self, payload: dict) -> dict:
        resp = self.post("/api/online/Session/InitToken", json_body=payload)
        return resp.json()

    def terminate_session(self) -> dict:
        resp = self.get("/api/online/Session/Terminate")
        return resp.json()

    # ------------------------------------------------------------------
    # Invoice endpoints
    # ------------------------------------------------------------------

    def send_invoice(self, payload: dict) -> dict:
        resp = self.post("/api/online/Invoice/Send", json_body=payload)
        return resp.json()

    def invoice_status(self, reference_number: str) -> dict:
        resp = self.get(f"/api/online/Invoice/Status/{reference_number}")
        return resp.json()

    def get_invoice(self, reference_number: str) -> bytes:
        resp = self.get(f"/api/online/Invoice/Get/{reference_number}")
        return resp.content

    def query_invoice(self, payload: dict) -> dict:
        resp = self.post("/api/online/Invoice/Query/Invoice/Async/Initiate", json_body=payload)
        return resp.json()

    def query_invoice_status(self, query_id: str) -> dict:
        resp = self.get(f"/api/online/Invoice/Query/Invoice/Async/Fetch/{query_id}/0/10")
        return resp.json()
