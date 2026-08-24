"""Cryptographic helpers for control-plane secrets and credentials."""

import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class SecretBox:
    def __init__(self, key: bytes):
        self._aesgcm = AESGCM(key)

    @classmethod
    def from_base64(cls, key: str) -> "SecretBox":
        try:
            decoded_key = base64.b64decode(key, validate=True)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "SAAS_MASTER_KEY must be valid base64"
            ) from exc
        if len(decoded_key) != 32:
            raise ValueError("SAAS_MASTER_KEY must decode to 32 bytes")
        return cls(decoded_key)

    def encrypt(self, plaintext: str, purpose: str) -> str:
        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(
            nonce,
            plaintext.encode("utf-8"),
            purpose.encode("utf-8"),
        )
        return base64.b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, ciphertext: str, purpose: str) -> str:
        payload = base64.b64decode(ciphertext, validate=True)
        nonce, encrypted = payload[:12], payload[12:]
        return self._aesgcm.decrypt(
            nonce, encrypted, purpose.encode("utf-8")
        ).decode("utf-8")


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def digest_sms_code(phone: str, code: str, key: bytes) -> str:
    digest_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"sms-login-code-v1",
    ).derive(key)
    message = f"{phone}:{code}".encode("utf-8")
    return hmac.new(digest_key, message, hashlib.sha256).hexdigest()
