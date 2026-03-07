"""Tests for ksef.auth — unit tests with mocked client."""

from __future__ import annotations

import hashlib
import base64

import pytest

from ksef.auth import _sign_challenge


def test_sign_challenge_deterministic():
    sig1 = _sign_challenge("challenge123", "token456")
    sig2 = _sign_challenge("challenge123", "token456")
    assert sig1 == sig2


def test_sign_challenge_sha256_base64():
    challenge = "abc"
    token = "def"
    expected_payload = (challenge + "|" + token).encode("utf-8")
    expected = base64.b64encode(hashlib.sha256(expected_payload).digest()).decode()
    assert _sign_challenge(challenge, token) == expected


def test_sign_challenge_changes_with_input():
    sig1 = _sign_challenge("challenge1", "token")
    sig2 = _sign_challenge("challenge2", "token")
    assert sig1 != sig2
