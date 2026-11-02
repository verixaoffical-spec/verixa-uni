"""Prints what the database stores for two-step verification, to check it by eye. Reads DATABASE_URL from .env.

    .venv\\Scripts\\python.exe scripts\\show_2fa_data.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the Windows console cannot print every character in an email

from sqlalchemy import func, select  # noqa: E402

from backend.db import RecoveryCode, SessionLocal, User, engine  # noqa: E402


def short(text: str | None, size: int = 22) -> str:
    return "-" if not text else text[:size] + "..."


with SessionLocal() as db:
    print(f"Database: {engine.url.render_as_string(hide_password=True)}\n")
    users = db.scalars(select(User).order_by(User.id)).all()
    print(f"{'id':>4}  {'email':<34} {'2FA':<4} {'secret (encrypted)':<26} {'last code step':<15} {'codes left':<10}")
    for u in users:
        left = db.scalar(select(func.count()).select_from(RecoveryCode)
                         .where(RecoveryCode.user_id == u.id, RecoveryCode.used_at.is_(None)))
        print(f"{u.id:>4}  {(u.email or '@' + (u.github_login or '?')):<34} {'on' if u.totp_secret else 'off':<4} "
              f"{short(u.totp_secret):<26} {str(u.totp_last_step or '-'):<15} {left if u.totp_secret else '-'}")

    codes = db.execute(select(User.email, RecoveryCode.code_hash, RecoveryCode.used_at)
                       .join(User, User.id == RecoveryCode.user_id).order_by(RecoveryCode.id)).all()
    print(f"\nRecovery codes ({len(codes)}): only hashes are stored")
    for email, code_hash, used_at in codes:
        print(f"  {email:<34} {short(code_hash, 30):<34} {'used ' + used_at.strftime('%Y-%m-%d %H:%M') if used_at else 'unused'}")

    print("\nWhat good looks like: secrets start with gAAAA (encrypted), hashes start with scrypt$, "
          "and a used recovery code shows the time it was used.")
