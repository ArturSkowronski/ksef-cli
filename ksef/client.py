"""httpx-based KSeF API v2 client with session management and error parsing."""

from __future__ import annotations

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
        # KSeF v2 wraps errors in various shapes
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
    """Thin httpx wrapper around the KSeF REST API v2."""

    def __init__(
        self,
        access_token: Optional[str] = None,
        base_url: str = KSEF_BASE_URL,
        timeout: float = TIMEOUT,
    ) -> None:
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
    # Auth endpoints (KSeF API v2)
    # ------------------------------------------------------------------

    def get_public_key(self) -> dict:
        """GET /api/v2/security/public-key-certificates — returns current KSeF public key."""
        resp = self.get("/api/v2/security/public-key-certificates")
        return resp.json()

    def auth_challenge(self, nip: str) -> dict:
        """POST /api/v2/auth/challenge — get a challenge for token-based auth."""
        resp = self.post(
            "/api/v2/auth/challenge",
            json_body={"contextIdentifier": {"type": "nip", "value": nip}},
        )
        return resp.json()

    def auth_ksef_token(self, payload: dict) -> dict:
        """POST /api/v2/auth/ksef-token — submit encrypted token, get authenticationToken."""
        resp = self.post("/api/v2/auth/ksef-token", json_body=payload)
        return resp.json()

    def auth_token_status(self, reference_number: str) -> dict:
        """GET /api/v2/auth/token/status/{ref} — poll until DONE."""
        resp = self.get(f"/api/v2/auth/token/status/{reference_number}")
        return resp.json()

    def auth_token_redeem(self, authentication_token: str) -> dict:
        """POST /api/v2/auth/token/redeem — exchange authenticationToken for accessToken."""
        resp = self.post(
            "/api/v2/auth/token/redeem",
            json_body={"authenticationToken": authentication_token},
        )
        return resp.json()

    def auth_logout(self) -> dict:
        """POST /api/v2/auth/logout — terminate session."""
        resp = self.post("/api/v2/auth/logout", json_body={})
        return resp.json()

    # ------------------------------------------------------------------
    # Invoice endpoints (KSeF API v2)
    # ------------------------------------------------------------------

    def send_invoice(self, payload: dict) -> dict:
        resp = self.post("/api/v2/invoice/send", json_body=payload)
        return resp.json()

    def invoice_status(self, reference_number: str) -> dict:
        resp = self.get(f"/api/v2/invoice/status/{reference_number}")
        return resp.json()

    def get_invoice(self, reference_number: str) -> bytes:
        resp = self.get(f"/api/v2/invoice/{reference_number}")
        return resp.content

    def query_invoice(self, payload: dict) -> dict:
        resp = self.post("/api/v2/invoice/query", json_body=payload)
        return resp.json()

    def query_invoice_status(self, query_id: str) -> dict:
        resp = self.get(f"/api/v2/invoice/query/{query_id}")
        return resp.json()
