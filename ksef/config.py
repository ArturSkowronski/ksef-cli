"""Read/write ~/.ksef/config.toml with enforced 600 permissions."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Optional

import tomllib
import tomli_w

CONFIG_DIR = Path.home() / ".ksef"
CONFIG_FILE = CONFIG_DIR / "config.toml"

_DEFAULT: dict = {
    "nip": "",
    "token": "",
    "session_token": "",
    "session_expiry": "",
}


def _ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Re-enforce permissions if dir already existed
    CONFIG_DIR.chmod(0o700)


def load() -> dict:
    """Load config from disk. Returns defaults if file doesn't exist."""
    _ensure_config_dir()
    if not CONFIG_FILE.exists():
        return dict(_DEFAULT)
    with CONFIG_FILE.open("rb") as f:
        data = tomllib.load(f)
    return {**_DEFAULT, **data}


def save(cfg: dict) -> None:
    """Write config to disk, enforcing 600 permissions."""
    _ensure_config_dir()
    content = tomli_w.dumps(cfg)
    # Write atomically via temp file
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.chmod(0o600)
    tmp.rename(CONFIG_FILE)


def get(key: str) -> str:
    """Convenience: load config and return a single value."""
    return load().get(key, "")


def set_values(**kwargs: str) -> None:
    """Merge kwargs into the existing config and save."""
    cfg = load()
    cfg.update({k: v for k, v in kwargs.items() if v is not None})
    save(cfg)


def require_session() -> str:
    """Return session token or exit with a helpful message."""
    import sys
    from rich.console import Console

    token = get("session_token")
    expiry = get("session_expiry")

    if not token:
        Console(stderr=True).print(
            "[red]No active session. Run `ksef auth login` first.[/red]"
        )
        sys.exit(1)

    # Check expiry if available
    if expiry:
        from datetime import datetime, timezone

        try:
            exp_dt = datetime.fromisoformat(expiry)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= exp_dt:
                Console(stderr=True).print(
                    "[red]Session expired. Run `ksef auth login` again.[/red]"
                )
                sys.exit(1)
        except ValueError:
            pass  # unparseable expiry — let the API reject it

    return token
