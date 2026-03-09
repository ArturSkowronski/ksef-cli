"""Cryptographic helpers for KSeF 2.0: RSA-OAEP + AES-256-CBC."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7


def load_public_key(public_key_pem: str):
    """Load an RSA public key from PEM or raw base64-DER."""
    if public_key_pem.strip().startswith("-----"):
        return serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    der_bytes = base64.b64decode(public_key_pem)
    return serialization.load_der_public_key(der_bytes)


def rsa_encrypt(plaintext: bytes, public_key_pem: str) -> bytes:
    """RSA-OAEP(SHA-256, MGF1(SHA-256)) encrypt. Returns raw ciphertext bytes."""
    pub_key = load_public_key(public_key_pem)
    return pub_key.encrypt(
        plaintext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )


def rsa_encrypt_b64(plaintext: bytes, public_key_pem: str) -> str:
    """RSA-OAEP encrypt and return base64-encoded ciphertext."""
    return base64.b64encode(rsa_encrypt(plaintext, public_key_pem)).decode("utf-8")


# ---------------------------------------------------------------------------
# AES-256-CBC for invoice encryption in sessions
# ---------------------------------------------------------------------------


def generate_session_keys() -> tuple[bytes, bytes]:
    """Generate a 256-bit AES key and 128-bit IV for session encryption."""
    aes_key = os.urandom(32)  # 256 bits
    iv = os.urandom(16)  # 128 bits
    return aes_key, iv


def encrypt_invoice(xml_bytes: bytes, aes_key: bytes, iv: bytes) -> bytes:
    """AES-256-CBC encrypt with PKCS#7 padding. Returns ciphertext (without IV prefix)."""
    padder = PKCS7(128).padder()
    padded = padder.update(xml_bytes) + padder.finalize()

    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def decrypt_invoice(ciphertext: bytes, aes_key: bytes, iv: bytes) -> bytes:
    """AES-256-CBC decrypt with PKCS#7 unpadding."""
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def encrypt_aes_key(aes_key: bytes, public_key_pem: str) -> str:
    """RSA-OAEP(SHA-256, MGF1) encrypt AES key → base64 string."""
    return rsa_encrypt_b64(aes_key, public_key_pem)
