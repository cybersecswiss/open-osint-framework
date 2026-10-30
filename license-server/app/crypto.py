"""
Encryption at rest for customer secrets held in the license DB.

## Why this exists

Encryption is **mandatory once a customer secret is stored here**. The
IdP backend secret and the notification settings are exactly that — an
SMTP password belongs to the customer's mail system, not to the operator,
and it lives in this database.

## What is protected

Only the columns that hold a secret *belonging to the customer*:
`idp_backend_secret`, `smtp_password`, `webhook_secret`. Not the licence
key or the agent key — those are operator-issued credentials the operator
must be able to read back and re-issue, and hiding them from ourselves
would break support without protecting anyone.

## The key

`LICENSE_KEK`, falling back to `secret_key` when unset so an existing
deployment keeps working with no new secret to distribute. Derivation is
the same shape as the framework's `services/api_keys.py`, deliberately:
one pattern to understand, not two.

⚠️ **Rotating the KEK makes every stored ciphertext unreadable.** There is
no re-encryption path in this service; the customer re-enters the SMTP
password and the agent installer re-pushes `idp_backend_secret`. Before
rotating, read docs/operations.en.md → "Secrets rotieren".

## Migration safety

A Fernet token is base64 of a 0x80 version byte and therefore always
starts `gAAAAA`. A stored value without that prefix is legacy plaintext
and is returned as-is, so rows written before this module existed keep
working and become ciphertext the next time they are saved. A value that
*does* carry the prefix but fails to decrypt is a real error — a KEK
mismatch — and is reported as such rather than silently handed on as if
it were plaintext. Confusing those two cases is how a decryption failure
turns into a credential leak into a log file.
"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.models import settings

log = logging.getLogger("license-server.crypto")

_FERNET_PREFIX = "gAAAAA"


def _kek() -> str:
    return (getattr(settings, "license_kek", "") or "").strip() or settings.secret_key


def _fernet() -> Fernet:
    digest = hashlib.sha256(_kek().encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str | None) -> str | None:
    """Encrypt a customer secret for storage. None/empty pass through so
    "clear this field" stays expressible — an empty string encrypted would
    be indistinguishable from a set-but-blank password."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt(stored: str | None) -> str:
    """Return the plaintext for a stored value. Legacy plaintext rows are
    returned unchanged; a genuine decrypt failure raises."""
    if not stored:
        return ""
    if not stored.startswith(_FERNET_PREFIX):
        # Written before this module existed. Re-saved as ciphertext on
        # the next write.
        return stored
    try:
        return _fernet().decrypt(stored.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Stored secret is Fernet ciphertext but cannot be decrypted — "
            "LICENSE_KEK does not match the one used to write it."
        ) from exc


def is_set(stored: str | None) -> bool:
    """Whether a secret column holds anything, without decrypting it.
    Used by the read path so a GET never has to touch the plaintext."""
    return bool(stored and stored.strip())
