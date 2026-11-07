"""Read-only facts about one account in the browser tests' own SQLite file, for the Forgot Password tests.

    python tests/e2e/db_check.py EMAIL [--password PW] [--token TOKEN]

Prints JSON. Never prints a password hash or a token: only short fingerprints for comparing before and after,
and yes/no answers. It opens the database read-only and refuses any file but the browser tests' own.
"""
import hashlib
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DB = Path(tempfile.gettempdir()) / "verixa-e2e.db"


def arg(name: str) -> str | None:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


def when(value: str) -> datetime:
    at = datetime.fromisoformat(value)
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def main() -> None:
    email, password, token = sys.argv[1], arg("--password"), arg("--token")
    db = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    user = db.execute("SELECT id, password_hash, session_version FROM users WHERE email = ?", (email,)).fetchone()
    if not user:
        print(json.dumps({"exists": False}))
        return
    stored = user["password_hash"] or ""
    rows = db.execute("SELECT token_hash, expires_at, created_at FROM password_resets WHERE user_id = ?", (user["id"],)).fetchall()
    now = datetime.now(timezone.utc)
    facts = {
        "exists": True,
        "hash_fingerprint": hashlib.sha256(stored.encode()).hexdigest()[:12],  # changes when the hash changes
        "hash_is_scrypt": stored.startswith("scrypt$"),
        "password_in_plain_text": bool(password) and (password in stored or password in json.dumps(dict(user))),
        "session_version": user["session_version"],
        "reset_rows": len(rows),
        "reset_rows_detail": [{
            "minutes_left": round((when(r["expires_at"]) - now).total_seconds() / 60, 1),
            "lifetime_minutes": round((when(r["expires_at"]) - when(r["created_at"])).total_seconds() / 60, 1),
            "stored_as_sha256_hex": len(r["token_hash"]) == 64 and all(c in "0123456789abcdef" for c in r["token_hash"]),
        } for r in rows],
        "reset_rows_total_all_users": db.execute("SELECT COUNT(*) FROM password_resets").fetchone()[0],
    }
    if token:
        digest = hashlib.sha256(token.encode()).hexdigest()
        facts["token_row_found"] = any(r["token_hash"] == digest for r in rows)
        facts["raw_token_stored"] = db.execute("SELECT COUNT(*) FROM password_resets WHERE token_hash = ?", (token,)).fetchone()[0] > 0
    print(json.dumps(facts))


if __name__ == "__main__":
    main()
