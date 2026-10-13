"""Secure storage for optional voice-provider credentials."""
from __future__ import annotations

import base64
import json
import os
import threading
from pathlib import Path


class SecretStoreError(RuntimeError):
    pass


class VoiceSecretStore:
    SERVICE = "ev.voice"
    _AAD = b"E.V voice secret vault v1"
    _ITERATIONS = 600_000

    def __init__(self, vault_path: str | Path):
        self.vault_path = Path(vault_path)
        self._lock = threading.RLock()
        self._vault_key: bytes | None = None
        self._vault_salt: bytes | None = None
        self._vault_values: dict[str, str] | None = None
        self._prefer_vault = self.vault_path.is_file()

    @staticmethod
    def _secure_keyring():
        try:
            import keyring
            backend = keyring.get_keyring()
        except Exception:  # noqa: BLE001 — optional keyring backend
            return None
        backend_name = type(backend).__name__.casefold()
        module_name = type(backend).__module__.casefold()
        if (getattr(backend, "priority", 0) <= 0
                or "fail" in backend_name
                or "plaintext" in backend_name
                or "keyrings.alt.file" in module_name):
            return None
        return keyring

    def status(self) -> dict:
        if self._prefer_vault or self.vault_path.is_file():
            crypto_available = self._crypto_available()
            return {
                "backend": "encrypted_vault",
                "available": crypto_available,
                "unlocked": self._vault_values is not None,
                "warning": ("OS keyring unavailable or vault selected; "
                            "fallback secrets use a passphrase-protected file "
                            "with mode 0600."
                            if crypto_available else
                            "Encrypted vault requires the optional cryptography package."),
            }
        keyring = self._secure_keyring()
        if keyring is not None:
            return {"backend": "os_keyring", "available": True,
                    "unlocked": True, "warning": None}
        vault_exists = self.vault_path.is_file()
        return {
            "backend": "encrypted_vault" if vault_exists else "unavailable",
            "available": self._crypto_available(),
            "unlocked": self._vault_values is not None,
            "warning": ("OS keyring unavailable; fallback secrets are "
                        "encrypted with a passphrase and stored with mode 0600."
                        if self._crypto_available() else
                        "No secure secret backend is available. Install keyring "
                        "or cryptography before configuring cloud credentials."),
        }

    @staticmethod
    def _crypto_available() -> bool:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _derive_key(passphrase: str, salt: bytes) -> bytes:
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        except ImportError as exc:
            raise SecretStoreError(
                "Encrypted vault requires the optional cryptography package.") from exc
        return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                          salt=salt,
                          iterations=VoiceSecretStore._ITERATIONS).derive(
                              passphrase.encode("utf-8"))

    def unlock_vault(self, passphrase: str, *, create: bool = False) -> None:
        if len(passphrase) < 12:
            raise SecretStoreError("Vault passphrase must be at least 12 characters.")
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            raise SecretStoreError(
                "Encrypted vault requires the optional cryptography package.") from exc

        with self._lock:
            if not self.vault_path.exists():
                if not create:
                    raise SecretStoreError("Encrypted vault has not been created.")
                self._vault_salt = os.urandom(16)
                self._vault_key = self._derive_key(passphrase,
                                                   self._vault_salt)
                self._vault_values = {}
                self._prefer_vault = True
                self._write_vault()
                return
            try:
                envelope = json.loads(self.vault_path.read_text(encoding="utf-8"))
                salt = base64.b64decode(envelope["salt"], validate=True)
                nonce = base64.b64decode(envelope["nonce"], validate=True)
                encrypted = base64.b64decode(envelope["ciphertext"], validate=True)
                key = self._derive_key(passphrase, salt)
                plaintext = AESGCM(key).decrypt(nonce, encrypted, self._AAD)
                values = json.loads(plaintext.decode("utf-8"))
                if not isinstance(values, dict) or not all(
                        isinstance(k, str) and isinstance(v, str)
                        for k, v in values.items()):
                    raise ValueError("invalid vault content")
            except Exception as exc:  # noqa: BLE001 — don't expose cipher details
                raise SecretStoreError(
                    "Could not unlock the encrypted voice vault; check the passphrase.") from exc
            self._vault_key = key
            self._vault_salt = salt
            self._vault_values = values
            self._prefer_vault = True

    def _write_vault(self) -> None:
        if self._vault_key is None or self._vault_values is None:
            raise SecretStoreError("Unlock the encrypted voice vault first.")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        self.vault_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.vault_path.parent, 0o700)
        salt = self._vault_salt or os.urandom(16)
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._vault_key).encrypt(
            nonce, json.dumps(self._vault_values, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8"),
            self._AAD)
        envelope = {"schema": 1, "kdf": "PBKDF2-HMAC-SHA256",
                    "iterations": self._ITERATIONS,
                    "salt": base64.b64encode(salt).decode("ascii"),
                    "nonce": base64.b64encode(nonce).decode("ascii"),
                    "ciphertext": base64.b64encode(ciphertext).decode("ascii")}
        temporary = self.vault_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(envelope) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.vault_path)

    def set(self, name: str, value: str) -> str:
        if not name or not name.replace("_", "").isalnum():
            raise SecretStoreError("Invalid secret name.")
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise SecretStoreError("Secret value is empty or invalid.")
        if len(value) > 8192:
            raise SecretStoreError("Secret value is too long.")
        with self._lock:
            if self._prefer_vault:
                if self._vault_values is None:
                    raise SecretStoreError("Encrypted voice vault is locked.")
                self._vault_values[name] = value
                self._write_vault()
                return name
            keyring = self._secure_keyring()
            if keyring is not None:
                try:
                    keyring.set_password(self.SERVICE, name, value)
                except Exception as exc:  # noqa: BLE001 — redact provider details
                    raise SecretStoreError(
                        f"OS keyring could not store {name}; no fallback plaintext was written.") from exc
            elif self._vault_values is not None:
                self._vault_values[name] = value
                self._write_vault()
            else:
                raise SecretStoreError(
                    "No unlocked secure secret backend. Install/use the OS keyring "
                    "or unlock an encrypted vault; credentials were not saved.")
        return name

    def get(self, name: str) -> str | None:
        with self._lock:
            if self._prefer_vault:
                if self._vault_values is None:
                    raise SecretStoreError("Encrypted voice vault is locked.")
                return self._vault_values.get(name)
            keyring = self._secure_keyring()
            if keyring is not None:
                try:
                    value = keyring.get_password(self.SERVICE, name)
                    if value is not None:
                        return value
                except Exception as exc:  # noqa: BLE001
                    raise SecretStoreError(
                        f"OS keyring could not read {name}.") from exc
            if self.vault_path.exists() and self._vault_values is None:
                raise SecretStoreError("Encrypted voice vault is locked.")
            return (self._vault_values or {}).get(name)

    def delete(self, name: str) -> bool:
        with self._lock:
            if self._prefer_vault:
                if self._vault_values is None:
                    raise SecretStoreError("Encrypted voice vault is locked.")
                if name not in self._vault_values:
                    return False
                del self._vault_values[name]
                self._write_vault()
                return True
            keyring = self._secure_keyring()
            if keyring is not None:
                try:
                    keyring.delete_password(self.SERVICE, name)
                    return True
                except Exception:
                    return False
            if self.vault_path.exists() and self._vault_values is None:
                raise SecretStoreError("Encrypted voice vault is locked.")
            if self._vault_values is None or name not in self._vault_values:
                return False
            del self._vault_values[name]
            self._write_vault()
            return True