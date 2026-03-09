"""Tests for ksef.crypto — AES-256-CBC + RSA-OAEP."""

from __future__ import annotations

import base64

import pytest

from ksef.crypto import (
    decrypt_invoice,
    encrypt_aes_key,
    encrypt_invoice,
    generate_session_keys,
    rsa_encrypt_b64,
)


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


def test_generate_session_keys_sizes():
    aes_key, iv = generate_session_keys()
    assert len(aes_key) == 32  # 256 bits
    assert len(iv) == 16  # 128 bits


def test_generate_session_keys_unique():
    k1, iv1 = generate_session_keys()
    k2, iv2 = generate_session_keys()
    assert k1 != k2
    assert iv1 != iv2


def test_encrypt_decrypt_invoice_roundtrip():
    aes_key, iv = generate_session_keys()
    plaintext = b"<Faktura>test invoice XML content here</Faktura>"
    ciphertext = encrypt_invoice(plaintext, aes_key, iv)
    assert ciphertext != plaintext
    assert len(ciphertext) >= len(plaintext)
    decrypted = decrypt_invoice(ciphertext, aes_key, iv)
    assert decrypted == plaintext


def test_encrypt_invoice_pkcs7_padding():
    """Ciphertext length should be a multiple of 16 (AES block size)."""
    aes_key, iv = generate_session_keys()
    # 17 bytes → padded to 32
    plaintext = b"x" * 17
    ciphertext = encrypt_invoice(plaintext, aes_key, iv)
    assert len(ciphertext) % 16 == 0
    assert len(ciphertext) == 32


def test_encrypt_aes_key_with_rsa():
    pem, private_key = _generate_test_rsa_key()
    aes_key = b"\x00" * 32
    encrypted_b64 = encrypt_aes_key(aes_key, pem)

    # Decrypt and verify
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    ciphertext = base64.b64decode(encrypted_b64)
    decrypted = private_key.decrypt(
        ciphertext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    assert decrypted == aes_key


def test_rsa_encrypt_b64_returns_valid_base64():
    pem, _ = _generate_test_rsa_key()
    result = rsa_encrypt_b64(b"test payload", pem)
    decoded = base64.b64decode(result)
    assert len(decoded) == 256  # 2048-bit RSA → 256-byte ciphertext
