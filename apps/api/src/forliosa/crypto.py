"""Keys derived from ``SESSION_SECRET`` and the small crypto helpers M5 needs.

Every purpose gets its own key (HKDF-SHA256 with a purpose label), so a value signed or encrypted for one purpose
can never be replayed as another:

* ``oauth-state``  — HMAC of the OAuth state cookie (``api/routes/auth.py``).
* ``feed-item-id`` — keyed hash behind the stable ids of computed group feed items (``services/sharing.py``).
* ``channel-webhook`` — Fernet (AES-128-CBC + HMAC-SHA256) encryption of Discord webhook URLs at rest.

Rotating ``SESSION_SECRET`` therefore also logs everyone out, makes stored webhook URLs undecryptable (the owner sets
the channel again) and re-keys feed item ids (comments on older trade items become unreachable).

Invite tokens and Telegram link codes are random (≥ 128 bits) and stored only as SHA-256 hashes (:func:`token_hash`):
they need no key, and a leaked database does not reveal a usable link.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from forliosa.config import get_settings

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def derived_key(purpose: str, secret: str | None = None) -> bytes:
    """32 bytes for ``purpose`` derived from ``SESSION_SECRET`` (HKDF-SHA256)."""
    raw = (secret if secret is not None else get_settings().session_secret).encode()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=f"forliosa/{purpose}".encode()).derive(raw)


def sign(purpose: str, message: bytes) -> bytes:
    return hmac.new(derived_key(purpose), message, hashlib.sha256).digest()


def verify(purpose: str, message: bytes, signature: bytes) -> bool:
    return hmac.compare_digest(sign(purpose, message), signature)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def crockford(data: bytes, length: int = 26) -> str:
    """The first ``length`` Crockford base32 characters of ``data`` (26 chars = 130 bits, like a ULID)."""
    value = int.from_bytes(data, "big")
    bits = len(data) * 8
    out = []
    for i in range(length):
        shift = bits - 5 * (i + 1)
        out.append(_CROCKFORD[(value >> shift) & 31] if shift >= 0 else _CROCKFORD[(value << -shift) & 31])
    return "".join(out)


def keyed_id(purpose: str, message: str) -> str:
    """A stable, unguessable 26-character id for ``message`` (HMAC-SHA256 under the purpose key)."""
    return crockford(sign(purpose, message.encode()))


def random_token(nbytes: int = 32) -> str:
    """URL-safe random token (32 bytes = 256 bits)."""
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    """SHA-256 hex digest: invite tokens and link codes are stored only as this."""
    return hashlib.sha256(token.encode()).hexdigest()


def _fernet(secret: str | None = None) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(derived_key("channel-webhook", secret)))


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret value (a Discord webhook URL) for storage."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str | None:
    """The stored secret, or None when it cannot be decrypted (``SESSION_SECRET`` was rotated, or tampering)."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return None
