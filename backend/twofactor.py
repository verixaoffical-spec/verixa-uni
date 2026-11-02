"""Two-step verification: the code step after the password, and the settings that turn it on and off.

Turning it on: /setup (password again) returns a QR code, /enable (a code from the app) confirms it and returns ten
recovery codes, shown once. Turning it off or making new recovery codes needs the password again and a current code.
Wrong answers return 400, never 401, because the dashboard treats 401 as a session that has ended.
"""
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from .accounts import Throttle, hash_password, verify_password
from .api import current_user
from .auth import _check_origin, _client_ip, _field_error, _locked, _sign_in, account_json
from .db import RecoveryCode, User, get_db, now
from .security import seal_totp, unseal_totp
from .totp import looks_like_totp, match_step, new_recovery_codes, new_secret, normalize_recovery, setup_details

router = APIRouter(prefix="/auth/2fa")
NO_STORE = {"Cache-Control": "no-store"}  # secrets and recovery codes must not linger in a cache
SETUP_SECONDS = 10 * 60
RECENT_SIGN_IN = 10 * 60  # accounts without a password confirm who they are by having signed in this recently
WRONG_CODE = "That code is not correct. Check your authenticator app and try again"

code_by_user = Throttle(limit=5, window=15 * 60)
code_by_ip = Throttle(limit=20, window=15 * 60)
password_by_user = Throttle(limit=5, window=15 * 60)


class CodeIn(BaseModel):
    code: str = Field("", max_length=50)


class PasswordIn(BaseModel):
    password: str = Field("", max_length=500)


class ConfirmIn(BaseModel):
    password: str = Field("", max_length=500)
    code: str = Field("", max_length=50)


# ---------- checking codes ----------

def _use_totp(db: Session, user: User, code: str) -> bool:
    """The update only matches when the code's step is newer than the last one used, so each code works once,
    even when two requests race."""
    step = match_step(unseal_totp(user.totp_secret), code)
    if step is None:
        return False
    newer = or_(User.totp_last_step.is_(None), User.totp_last_step < step)
    used = db.execute(update(User).where(User.id == user.id, newer).values(totp_last_step=step)).rowcount
    db.commit()
    return bool(used)


def _use_recovery(db: Session, user: User, code: str) -> bool:
    code = normalize_recovery(code)
    if len(code) != 10:
        return False
    unused = select(RecoveryCode).where(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None))
    for row in db.scalars(unused).all():
        if verify_password(code, row.code_hash):
            still_unused = RecoveryCode.id == row.id, RecoveryCode.used_at.is_(None)
            used = db.execute(update(RecoveryCode).where(*still_unused).values(used_at=now())).rowcount
            db.commit()
            return bool(used)
    return False


def _second_factor(db: Session, user: User, code: str) -> str | None:
    """'app' or 'recovery' for a good code, None for a wrong one."""
    if looks_like_totp(code):
        return "app" if _use_totp(db, user, code) else None
    return "recovery" if _use_recovery(db, user, code) else None


def _counted(request: Request, user: User, check):
    """Runs check() and returns its answer. A None answer counts as a failure, and five lock the account's codes
    for 15 minutes, whichever session or address they come from."""
    keys = ((code_by_user, str(user.id)), (code_by_ip, _client_ip(request)))
    if wait := max(t.retry_after(k) for t, k in keys):
        raise _locked(wait)
    result = check()
    if result is None:
        for t, k in keys:
            t.fail(k)
        if wait := code_by_user.retry_after(str(user.id)):
            raise _locked(wait)
        raise _field_error("code", WRONG_CODE, 400)
    code_by_user.clear(str(user.id))
    return result


def _confirm_identity(request: Request, user: User, password: str) -> None:
    """Asks for the password again. Accounts made with GitHub have none, so they must have signed in recently."""
    if not user.password_hash:
        if time.time() - request.session.get("auth_at", 0) > RECENT_SIGN_IN:
            raise _field_error("reauth", "For your security, sign in again to change this setting", 400)
        return
    key = str(user.id)
    if wait := password_by_user.retry_after(key):
        raise _locked(wait)
    if not verify_password(password, user.password_hash):
        password_by_user.fail(key)
        if wait := password_by_user.retry_after(key):
            raise _locked(wait)
        raise _field_error("password", "That password is not correct", 400)
    password_by_user.clear(key)


def _codes_left(db: Session, user: User) -> int:
    unused = RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None)
    return db.scalar(select(func.count()).select_from(RecoveryCode).where(*unused))


def _new_recovery_codes(db: Session, user: User) -> list[str]:
    """Replaces every recovery code. Only the hashes are kept, so the plain codes are shown this one time."""
    codes = new_recovery_codes()
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    db.add_all(RecoveryCode(user_id=user.id, code_hash=hash_password(normalize_recovery(c))) for c in codes)
    return codes


def _sign_out_other_sessions(request: Request, db: Session, user: User) -> None:
    user.session_version += 1
    db.commit()
    _sign_in(request, user)  # this session carries the new version and stays signed in


# ---------- the second step of signing in ----------

@router.post("/verify")
def verify(body: CodeIn, request: Request, db: Session = Depends(get_db)):
    _check_origin(request)
    uid = request.session.get("mfa_uid")
    user = db.get(User, uid) if uid else None
    if not user or not user.totp_secret or time.time() > request.session.get("mfa_until", 0):
        request.session.pop("mfa_uid", None)
        request.session.pop("mfa_until", None)
        raise HTTPException(401, "Your sign in timed out. Enter your password again")
    kind = _counted(request, user, lambda: _second_factor(db, user, body.code))
    _sign_in(request, user)
    return {"account": account_json(user), "recovery_codes_left": _codes_left(db, user) if kind == "recovery" else None}


# ---------- settings ----------

@router.get("")
def status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"enabled": bool(user.totp_secret), "has_password": bool(user.password_hash),
            "recovery_codes_left": _codes_left(db, user) if user.totp_secret else 0}


@router.post("/setup")
def setup(body: PasswordIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_origin(request)
    if user.totp_secret:
        raise HTTPException(409, "Two-step verification is already on")
    _confirm_identity(request, user, body.password)
    secret = new_secret()
    user.totp_pending = seal_totp(secret)
    db.commit()
    request.session["totp_setup_until"] = int(time.time()) + SETUP_SECONDS
    return JSONResponse(setup_details(secret, user.email or user.github_login or f"account {user.id}"), headers=NO_STORE)


@router.post("/enable")
def enable(body: CodeIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_origin(request)
    if user.totp_secret:
        raise HTTPException(409, "Two-step verification is already on")
    if not user.totp_pending or time.time() > request.session.get("totp_setup_until", 0):
        raise _field_error("setup", "Setup timed out. Start again to get a new QR code", 400)
    pending = unseal_totp(user.totp_pending)
    step = _counted(request, user, lambda: match_step(pending, body.code))
    user.totp_secret, user.totp_pending, user.totp_last_step = user.totp_pending, None, step
    codes = _new_recovery_codes(db, user)
    request.session.pop("totp_setup_until", None)
    _sign_out_other_sessions(request, db, user)
    return JSONResponse({"account": account_json(user), "recovery_codes": codes}, headers=NO_STORE)


@router.post("/disable")
def disable(body: ConfirmIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_origin(request)
    if not user.totp_secret:
        raise HTTPException(409, "Two-step verification is already off")
    _confirm_identity(request, user, body.password)
    _counted(request, user, lambda: _second_factor(db, user, body.code))
    user.totp_secret = user.totp_last_step = None
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    _sign_out_other_sessions(request, db, user)
    return {"account": account_json(user)}


@router.post("/recovery-codes")
def regenerate(body: ConfirmIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_origin(request)
    if not user.totp_secret:
        raise HTTPException(409, "Turn on two-step verification first")
    _confirm_identity(request, user, body.password)
    _counted(request, user, lambda: _second_factor(db, user, body.code))
    codes = _new_recovery_codes(db, user)
    db.commit()
    return JSONResponse({"recovery_codes": codes}, headers=NO_STORE)
