import base64
import hashlib
import hmac
import logging

from cryptography.fernet import Fernet

from .settings import settings

# OAuth tokens are encrypted before they reach the database.
_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest()))


def seal(text: str) -> str:
    return _fernet.encrypt(text.encode()).decode()


def unseal(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()


# Authenticator secrets have their own key, so changing SECRET_KEY never locks anyone out of two-step verification.
if not settings.totp_encryption_key:
    logging.warning("TOTP_ENCRYPTION_KEY is not set. Two-step secrets use a key derived from SECRET_KEY. See .env.example")
_totp_fernet = Fernet(settings.totp_encryption_key or base64.urlsafe_b64encode(
    hashlib.sha256(b"verixa-totp\0" + settings.secret_key.encode()).digest()))


def seal_totp(secret: str) -> str:
    return _totp_fernet.encrypt(secret.encode()).decode()


def unseal_totp(token: str) -> str:
    return _totp_fernet.decrypt(token.encode()).decode()


def valid_signature(body: bytes, header: str | None) -> bool:
    """Checks GitHub's X-Hub-Signature-256 header against our webhook secret."""
    if not header:
        return False
    expected = "sha256=" + hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)
