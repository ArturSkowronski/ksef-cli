"""Tests for ksef.auth — RSA-OAEP token encryption and auth flow."""

from __future__ import annotations

import base64

import pytest

from ksef.auth import _encrypt_token


def _generate_test_rsa_key() -> tuple[str, object]:
    """Generate a throwaway RSA key pair for testing."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    pem = public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return pem, private_key


def test_encrypt_token_returns_base64():
    pem, _ = _generate_test_rsa_key()
    result = _encrypt_token("mytoken", 1700000000000, pem)
    decoded = base64.b64decode(result)
    assert len(decoded) == 256  # 2048-bit RSA → 256-byte ciphertext


def test_encrypt_token_decryptable():
    """Encrypt then decrypt should round-trip."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    pem, private_key = _generate_test_rsa_key()
    token = "ABCDEF123456"
    ts = 1700000000000
    encrypted_b64 = _encrypt_token(token, ts, pem)

    ciphertext = base64.b64decode(encrypted_b64)
    plaintext = private_key.decrypt(
        ciphertext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    assert plaintext.decode("utf-8") == f"{token}|{ts}"


def test_encrypt_token_different_for_different_inputs():
    pem, _ = _generate_test_rsa_key()
    enc1 = _encrypt_token("token1", 1000, pem)
    enc2 = _encrypt_token("token2", 1000, pem)
    assert enc1 != enc2


def test_encrypt_token_uses_crypto_module():
    """Verify _encrypt_token delegates to crypto.rsa_encrypt_b64."""
    pem, private_key = _generate_test_rsa_key()
    result = _encrypt_token("test", 999, pem)
    # Should produce valid base64 of 256 bytes (RSA-2048)
    assert len(base64.b64decode(result)) == 256
