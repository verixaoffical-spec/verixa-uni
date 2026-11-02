"""Two-step verification codes: authenticator app codes (TOTP) and recovery codes. Pure functions, no database."""
import hmac
import re
import secrets
import time

import pyotp
import segno

ISSUER = "Verixa"
STEP = 30  # seconds per code, the authenticator app default
RECOVERY_COUNT = 10
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0, o, 1, i or l, which are easy to misread


def new_secret() -> str:
    return pyotp.random_base32()  # 160 random bits


def setup_details(secret: str, account: str) -> dict:
    """What the setup screen shows: a QR code for the app to scan, and the key to type in by hand."""
    uri = pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=ISSUER)
    return {"qr": segno.make(uri, error="m").svg_data_uri(dark="#000", light="#fff", border=2),
            "secret": " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))}


def match_step(secret: str, code: str, at: float | None = None) -> int | None:
    """The time step the code belongs to, or None when it is wrong. One step either side allows for clock drift.
    The caller stores the step and refuses any step it has already seen, so a code cannot be used twice."""
    code = re.sub(r"\s", "", code or "")
    if not re.fullmatch(r"\d{6}", code):
        return None
    totp = pyotp.TOTP(secret)
    now = int((time.time() if at is None else at) // STEP)
    for step in (now - 1, now, now + 1):
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def looks_like_totp(code: str) -> bool:
    return bool(re.fullmatch(r"\d{6}", re.sub(r"\s", "", code or "")))


def new_recovery_codes() -> list[str]:
    """Ten codes of ten characters, shown as abcde-fghjk. About 49 bits each."""
    codes = ["".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(10)) for _ in range(RECOVERY_COUNT)]
    return [f"{c[:5]}-{c[5:]}" for c in codes]


def normalize_recovery(code: str) -> str:
    """Accepts any case, spaces and dashes, so a code typed from paper still works."""
    return re.sub(r"[\s-]", "", code or "").lower()
