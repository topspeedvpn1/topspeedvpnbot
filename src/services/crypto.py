from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


class CryptoService:
    def __init__(self, app_secret: str) -> None:
        digest = hashlib.sha256(app_secret.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
