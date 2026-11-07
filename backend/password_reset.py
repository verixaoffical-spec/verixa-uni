"""Forgot password: a single use link sent by email, valid for 30 minutes.

The link carries a random token after `#`, so it never reaches server or tunnel logs. Only a SHA-256 hash of the
token is stored. Asking for a link always gets the same answer, whether or not the email has an account, so the
form cannot be used to find out who uses Verixa. Setting a new password ends every session of the account, and
two-step verification still asks for its code at the next log in.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import auth
from .accounts import Throttle, email_problem, hash_password, normalize_email, password_problem
from .auth import _check_origin, _client_ip, _field_error, _too_many
from .db import PasswordReset, User, get_db, now
from .mailer import send_email
from .settings import settings

router = APIRouter(prefix="/auth")

RESET_MINUTES = 30
SENT = "If an account uses that email, we have sent it a link to reset the password. Check your inbox and spam folder."
INVALID = "This reset link is not valid, or it has expired. Ask for a new one."
NO_STORE = {"Cache-Control": "no-store"}

forgot_by_ip = Throttle(limit=10, window=60 * 60)
forgot_by_email = Throttle(limit=3, window=60 * 60)  # nobody can fill someone's inbox with reset emails
reset_by_ip = Throttle(limit=20, window=15 * 60)    # guessing a 256 bit token is hopeless, but there is no reason to allow it


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(at: datetime) -> datetime:
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)  # SQLite gives back times without a zone


def reset_link(token: str) -> str:
    return f"{settings.public_url}/reset-password#token={token}"


def _email_text(name: str, link: str) -> str:
    return (f"Hi {name},\n\n"
            "Someone asked to reset the password of your Verixa account.\n"
            f"Open this link within {RESET_MINUTES} minutes to choose a new password:\n\n"
            f"{link}\n\n"
            "The link works once. If you did not ask for this, ignore this email and your password stays the same.\n\n"
            "Verixa\n")


class ForgotIn(BaseModel):
    email: str = Field("", max_length=500)


class ResetIn(BaseModel):
    token: str = Field("", max_length=200)
    password: str = Field("", max_length=500)


@router.post("/forgot", status_code=202)
def forgot(body: ForgotIn, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    _check_origin(request)
    email = normalize_email(body.email)
    if problem := email_problem(email):
        raise _field_error("email", problem)
    ip = _client_ip(request)
    if wait := max(forgot_by_ip.retry_after(ip), forgot_by_email.retry_after(email)):
        return _too_many(wait)
    forgot_by_ip.fail(ip)
    forgot_by_email.fail(email)

    user = db.scalar(select(User).where(User.email == email))
    if user:
        token = secrets.token_urlsafe(32)
        db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))  # only the newest link works
        db.add(PasswordReset(user_id=user.id, token_hash=token_hash(token),
                             expires_at=now() + timedelta(minutes=RESET_MINUTES)))
        db.commit()
        background.add_task(send_email, email, "Reset your Verixa password", _email_text(user.name or "there", reset_link(token)))
    return {"message": SENT}


@router.post("/reset")
def reset(body: ResetIn, request: Request, db: Session = Depends(get_db)):
    _check_origin(request)
    ip = _client_ip(request)
    if wait := reset_by_ip.retry_after(ip):
        return _too_many(wait)
    row = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == token_hash(body.token))) if body.token else None
    user = db.get(User, row.user_id) if row else None
    if not row or not user or _aware(row.expires_at) <= now():
        reset_by_ip.fail(ip)
        raise HTTPException(400, INVALID, headers=NO_STORE)
    if problem := password_problem(body.password, user.email or "", user.name or ""):
        raise _field_error("password", problem)

    user.password_hash = hash_password(body.password)
    user.session_version += 1  # every signed in session ends, including one an attacker may have
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    db.commit()
    if user.email:
        auth.login_by_email.clear(user.email)  # a locked out owner can log in straight away
    request.session.clear()
    return {"message": "Your password has been changed. Log in with your new password."}
