"""Sign up with email: the account is only created once the person proves the email is theirs.

Sign up checks the form, then keeps the name, email and an already hashed password in pending_signups and emails a
single use link. Nothing is added to users yet. Opening the link and pressing Verify moves the sign up into users and
signs the person in. The token sits after `#`, so it never reaches server or tunnel logs, and only its SHA-256 hash is
stored. An unconfirmed sign up expires after 24 hours, and signing up again with the same email replaces it.
"""
import secrets
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .accounts import Throttle, email_problem, hash_password, name_problem, normalize_email, normalize_name, password_problem
from .auth import _check_origin, _client_ip, _field_error, _sign_in, _too_many, account_json, signup_by_ip
from .db import PendingSignup, User, get_db, now
from .mailer import send_email
from .password_reset import NO_STORE, _aware, token_hash
from .settings import settings

router = APIRouter(prefix="/auth")

VERIFY_HOURS = 24
TAKEN = "An account with this email already exists. Log in instead"
INVALID = "This verification link is not valid, or it has expired. Sign up again to get a new one."

signup_by_email = Throttle(limit=3, window=60 * 60)  # nobody can fill someone's inbox with verification emails
verify_by_ip = Throttle(limit=20, window=15 * 60)


def verify_link(token: str) -> str:
    return f"{settings.public_url}/verify-email#token={token}"


def _email_text(name: str, link: str) -> str:
    return (f"Hi {name},\n\n"
            "Welcome to Verixa. Confirm this is your email to create your account.\n"
            f"Open this link within {VERIFY_HOURS} hours and press Verify:\n\n"
            f"{link}\n\n"
            "If you did not sign up for Verixa, ignore this email and no account is created.\n\n"
            "Verixa\n")


class SignupIn(BaseModel):
    name: str = Field("", max_length=500)
    email: str = Field("", max_length=500)
    password: str = Field("", max_length=500)


class VerifyIn(BaseModel):
    token: str = Field("", max_length=200)


@router.post("/signup", status_code=202)
def signup(body: SignupIn, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    _check_origin(request)
    name, email = normalize_name(body.name), normalize_email(body.email)
    for field, problem in (("name", name_problem(name)), ("email", email_problem(email)),
                           ("password", password_problem(body.password, email, name))):
        if problem:
            raise _field_error(field, problem)
    ip = _client_ip(request)
    if wait := max(signup_by_ip.retry_after(ip), signup_by_email.retry_after(email)):
        return _too_many(wait)
    signup_by_ip.fail(ip)  # counted every time, so nobody can test a long list of emails to see who has an account
    if db.scalar(select(User.id).where(User.email == email)):
        raise _field_error("email", TAKEN, 409)
    signup_by_email.fail(email)

    token = secrets.token_urlsafe(32)
    db.execute(delete(PendingSignup).where(PendingSignup.expires_at < now()))  # forgotten sign ups are cleared
    db.execute(delete(PendingSignup).where(PendingSignup.email == email))     # only the newest link works
    db.add(PendingSignup(email=email, name=name, password_hash=hash_password(body.password),
                         token_hash=token_hash(token), expires_at=now() + timedelta(hours=VERIFY_HOURS)))
    db.commit()
    background.add_task(send_email, email, "Verify your email for Verixa", _email_text(name, verify_link(token)))
    return {"verify": True, "email": email}


@router.post("/verify-email")
def verify_email(body: VerifyIn, request: Request, db: Session = Depends(get_db)):
    _check_origin(request)
    ip = _client_ip(request)
    if wait := verify_by_ip.retry_after(ip):
        return _too_many(wait)
    pending = db.scalar(select(PendingSignup).where(PendingSignup.token_hash == token_hash(body.token))) if body.token else None
    if not pending or _aware(pending.expires_at) <= now():
        verify_by_ip.fail(ip)
        raise HTTPException(400, INVALID, headers=NO_STORE)

    pending_id = pending.id
    user = User(email=pending.email, name=pending.name, password_hash=pending.password_hash)
    db.delete(pending)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # the email got an account another way while the link waited
        db.rollback()
        db.execute(delete(PendingSignup).where(PendingSignup.id == pending_id))
        db.commit()
        raise HTTPException(409, TAKEN, headers=NO_STORE)
    _sign_in(request, user)
    return {"account": account_json(user)}
