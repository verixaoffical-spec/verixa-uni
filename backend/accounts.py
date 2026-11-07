"""Email and password accounts: input rules, password hashing and login throttling. Pure functions, no database."""
import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
import unicodedata

EMAIL_MAX = 254
NAME_MAX = 80
PASSWORD_MIN = 8
PASSWORD_MAX = 128
PASSWORD_MIN_DISTINCT = 4  # aaaaaaa1 and a1a1a1a1 pass every other rule

# Plain ASCII addresses only, so no markup, control characters or look-alike letters can get in. Expects lowercase.
# A top level domain is letters, or xn-- for an international one.
EMAIL_RE = re.compile(r"^[a-z0-9_%+'-]+(?:\.[a-z0-9_%+'-]+)*@(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:[a-z]{2,}|xn--[a-z0-9-]+)$")
NAME_PUNCTUATION = " '’.-"
COMMON_PASSWORDS = {
    "password", "password1", "password12", "password123", "12345678", "123456789", "1234567890", "qwerty123",
    "qwertyuiop", "iloveyou1", "letmein123", "welcome1", "welcome123", "admin123", "abc12345", "passw0rd",
    "11111111", "00000000", "verixa123", "monkey123", "dragon123", "football1", "baseball1", "sunshine1",
}

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


def normalize_email(email: str) -> str:
    return unicodedata.normalize("NFKC", email or "").strip().lower()


def normalize_name(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name or "").split())


def email_problem(email: str) -> str | None:
    """Expects a normalized email."""
    if not email:
        return "Enter your email address"
    if len(email) > EMAIL_MAX or len(email.split("@")[0]) > 64 or not EMAIL_RE.fullmatch(email):
        return "Enter a valid email address, like name@company.com"
    return None


def name_problem(name: str) -> str | None:
    """Expects a normalized name."""
    if not name:
        return "Enter your name"
    if len(name) > NAME_MAX:
        return f"Use {NAME_MAX} characters or fewer"
    is_letter = lambda c: unicodedata.category(c)[0] in "LM"
    if not is_letter(name[0]) or not all(is_letter(c) or c in NAME_PUNCTUATION for c in name):
        return "Use letters, spaces and simple punctuation only"
    if len(name) < 2:
        return "Use at least 2 characters"
    return None


def password_problem(password: str, email: str = "", name: str = "") -> str | None:
    """Passwords are never trimmed: spaces count like any other character."""
    if not password:
        return "Enter a password"
    if len(password) < PASSWORD_MIN:
        return f"Use at least {PASSWORD_MIN} characters"
    if len(password) > PASSWORD_MAX:
        return f"Use {PASSWORD_MAX} characters or fewer"
    if not password.strip():
        return "A password cannot be only spaces"
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Use at least one letter and one number"
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS or len(set(lowered)) < PASSWORD_MIN_DISTINCT:
        return "That password is too common. Pick something less guessable"
    local = email.split("@")[0]
    if (len(local) >= 4 and local in lowered) or (email and lowered == email):
        return "Do not use your email address in the password"
    if name and len(name) >= 4 and name.lower().replace(" ", "") in lowered.replace(" ", ""):
        return "Do not use your name in the password"
    return None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    b64 = lambda b: base64.b64encode(b).decode()
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        # Still do the work, so an unknown email takes as long as a wrong password.
        hashlib.scrypt(password.encode(), salt=b"verixa-dummy-salt", dklen=32, **_SCRYPT)
        return False
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), dklen=32,
                                n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, base64.b64decode(digest))


def safe_next(target: str | None, default: str) -> str:
    """Only same-site paths are allowed after sign in, so the page can never be used to bounce people elsewhere."""
    if not target or len(target) > 500:
        return default
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        return default
    if any(ord(c) < 32 for c in target) or re.split(r"[?#]", target)[0] in ("/login", "/signup"):
        return default
    return target


class Throttle:
    """Counts failed attempts per key in a sliding window. In memory, so it resets when the server restarts."""

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, at: float) -> list[float]:
        stamps = [t for t in self._fails.get(key, []) if at - t < self.window]
        if stamps:
            self._fails[key] = stamps
        else:
            self._fails.pop(key, None)
        return stamps

    def retry_after(self, key: str, at: float | None = None) -> int:
        """Seconds until the key may try again, or 0 when it is not blocked."""
        at = time.monotonic() if at is None else at
        with self._lock:
            stamps = self._recent(key, at)
            if len(stamps) < self.limit:
                return 0
            return max(1, int(stamps[-self.limit] + self.window - at + 0.999))

    def fail(self, key: str, at: float | None = None) -> None:
        at = time.monotonic() if at is None else at
        with self._lock:
            self._fails[key] = self._recent(key, at) + [at]

    def clear(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
