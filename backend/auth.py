"""Accounts and sign in.

A Verixa account starts with an email and password, or with GitHub. Connecting GitHub and Atlassian for the
workspace happens after that, from the dashboard, and always attaches to the account that is signed in.
"""
import secrets
import time
import urllib.parse as up

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .accounts import (
    Throttle, email_problem, hash_password, name_problem, normalize_email, normalize_name, password_problem,
    safe_next, verify_password,
)
from .db import User, get_db
from .integrations import (
    atlassian_authorize_url, atlassian_exchange, github_authorize_url, github_exchange, store_atlassian_tokens,
)
from .security import seal
from .settings import settings

router = APIRouter(prefix="/auth")
APP = "/verixa_prototype.html"
LOGIN = "/login"

PENDING_SECONDS = 5 * 60  # time allowed to enter the two-step code after the password

login_by_email = Throttle(limit=5, window=15 * 60)
login_by_ip = Throttle(limit=30, window=15 * 60)
signup_by_ip = Throttle(limit=10, window=60 * 60)


def signed_in_user(request: Request, db: Session) -> User | None:
    """The account behind the session cookie. A cookie for an account that no longer exists is dropped."""
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    # session_version changes when two-step verification is turned on or off, which signs out every other session
    if uid and (not user or request.session.get("ver", 0) != user.session_version):
        request.session.clear()
        return None
    return user


def account_json(user: User) -> dict:
    return {"name": user.name or user.github_name or user.github_login or "Verixa user",
            "email": user.email, "github_login": user.github_login, "two_factor": bool(user.totp_secret)}


def _sign_in(request: Request, user: User) -> None:
    request.session.clear()  # a fresh session on every sign in, so an old cookie can never be promoted
    request.session["uid"] = user.id
    request.session["ver"] = user.session_version
    request.session["auth_at"] = int(time.time())  # security settings ask accounts without a password to be recent


def _sign_in_or_ask_code(request: Request, user: User) -> bool:
    """Signs in, or when two-step verification is on, only remembers who passed the first step.
    The session has no uid until the code is checked, so every protected page and API still refuses it."""
    if not user.totp_secret:
        _sign_in(request, user)
        return True
    request.session.clear()
    request.session["mfa_uid"] = user.id
    request.session["mfa_until"] = int(time.time()) + PENDING_SECONDS
    return False


def _check_origin(request: Request) -> None:
    """Browsers send Origin on every POST. Refuse forms posted from another site."""
    origin = request.headers.get("origin")
    if not origin:
        return
    allowed = {request.headers.get("host"), up.urlsplit(settings.public_url).netloc}
    if up.urlsplit(origin).netloc not in allowed:
        raise HTTPException(403, "This request came from another site")


def _client_ip(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    if host in ("127.0.0.1", "::1"):
        # Behind a local tunnel such as ngrok every visitor arrives from loopback, and the tunnel appends the real
        # address to X-Forwarded-For. Take the last entry: earlier ones are whatever the visitor chose to send.
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        return forwarded or host
    return host


def _field_error(field: str, message: str, status: int = 422) -> HTTPException:
    return HTTPException(status, {"field": field, "message": message})


def _locked(seconds: int) -> HTTPException:
    minutes = max(1, round(seconds / 60))
    return HTTPException(
        429, {"message": f"Too many attempts. Try again in {minutes} minute{'s' if minutes > 1 else ''}",
              "retry_after": seconds},
        headers={"Retry-After": str(seconds)},
    )


def _too_many(seconds: int) -> JSONResponse:
    error = _locked(seconds)
    return JSONResponse({"detail": error.detail}, status_code=429, headers=error.headers)


class SignupIn(BaseModel):
    name: str = Field("", max_length=500)
    email: str = Field("", max_length=500)
    password: str = Field("", max_length=500)


class LoginIn(BaseModel):
    email: str = Field("", max_length=500)
    password: str = Field("", max_length=500)


@router.post("/signup", status_code=201)
def signup(body: SignupIn, request: Request, db: Session = Depends(get_db)):
    _check_origin(request)
    name, email = normalize_name(body.name), normalize_email(body.email)
    for field, problem in (("name", name_problem(name)), ("email", email_problem(email)),
                           ("password", password_problem(body.password, email, name))):
        if problem:
            raise _field_error(field, problem)
    ip = _client_ip(request)
    if wait := signup_by_ip.retry_after(ip):
        return _too_many(wait)
    if db.scalar(select(User.id).where(User.email == email)):
        signup_by_ip.fail(ip)  # counted too, so nobody can test a long list of emails to see who has an account
        raise _field_error("email", "An account with this email already exists. Log in instead", 409)
    user = User(email=email, name=name, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # two sign ups with the same email at the same moment
        db.rollback()
        raise _field_error("email", "An account with this email already exists. Log in instead", 409)
    signup_by_ip.fail(ip)
    _sign_in(request, user)
    return {"account": account_json(user)}


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    _check_origin(request)
    email = normalize_email(body.email)
    if problem := email_problem(email):
        raise _field_error("email", problem)
    if not body.password:
        raise _field_error("password", "Enter your password")
    keys = ((login_by_email, email), (login_by_ip, _client_ip(request)))
    if wait := max(t.retry_after(k) for t, k in keys):
        return _too_many(wait)
    user = db.scalar(select(User).where(User.email == email))
    if not verify_password(body.password, user.password_hash if user else None):
        for t, k in keys:
            t.fail(k)
        if wait := login_by_email.retry_after(email):
            return _too_many(wait)
        raise _field_error("password", "Email or password is incorrect", 401)
    login_by_email.clear(email)
    if not _sign_in_or_ask_code(request, user):
        return {"two_factor": True}
    return {"account": account_json(user)}


@router.post("/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db)):
    """Ends every session of the account. A session lives in its cookie, so this is what makes a stolen copy useless."""
    _check_origin(request)
    if user := signed_in_user(request, db):
        user.session_version += 1
        db.commit()
    request.session.clear()
    return Response(status_code=204)


# ---------- GitHub and Atlassian ----------

def _begin(request: Request, authorize_url) -> RedirectResponse:
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    return RedirectResponse(authorize_url(state))


def _fail(request: Request, message: str) -> RedirectResponse:
    page = APP if request.session.get("uid") else LOGIN
    return RedirectResponse(f"{page}?error={up.quote(message)}")


def _state_ok(request: Request, state: str | None) -> bool:
    return bool(state) and state == request.session.pop("oauth_state", None)


@router.get("/github")
def github_sign_in(request: Request):
    """Continue with GitHub from the log in and sign up pages."""
    return _begin(request, github_authorize_url)


@router.get("/start")
def start(request: Request, db: Session = Depends(get_db)):
    """Connects whichever of GitHub and Atlassian the signed in account is still missing."""
    user = signed_in_user(request, db)
    if not user:
        return RedirectResponse(f"{LOGIN}?next={up.quote(APP)}")
    if not user.github_token:
        return _begin(request, github_authorize_url)
    if not user.atlassian_token:
        return _begin(request, atlassian_authorize_url)
    return RedirectResponse(APP)


@router.post("/relink", status_code=204)
def relink(request: Request, db: Session = Depends(get_db)):
    """Forgets saved GitHub and Atlassian tokens that stopped working, so /auth/start asks for both again."""
    _check_origin(request)
    user = signed_in_user(request, db)
    if not user:
        raise HTTPException(401, "Sign in first")
    user.github_token = user.atlassian_token = user.atlassian_refresh = user.atlassian_expires_at = None
    db.commit()
    return Response(status_code=204)


@router.get("/github/callback")
def github_callback(request: Request, code: str | None = None, state: str | None = None,
                    error: str | None = None, db: Session = Depends(get_db)):
    if error or not code:
        return _fail(request, "GitHub sign in was cancelled")
    if not _state_ok(request, state):
        return _fail(request, "Sign in expired. Please try again")
    try:
        token, me = github_exchange(code)
    except HTTPException as exc:
        return _fail(request, str(exc.detail))
    current = signed_in_user(request, db)
    owner = db.scalar(select(User).where(User.github_id == me["id"]))
    if current and owner and owner.id != current.id:
        return _fail(request, f"GitHub account {me['login']} is already linked to another Verixa account")
    user = current or owner or User(github_id=me["id"], name=normalize_name(me.get("name") or me["login"])[:80])
    user.github_id = me["id"]
    user.github_login = me["login"]
    user.github_name = (me.get("name") or "")[:200] or None  # GitHub allows longer names than the column holds
    user.github_token = seal(token)
    db.add(user)
    db.commit()
    if not current:
        if not _sign_in_or_ask_code(request, user):
            return RedirectResponse(f"{LOGIN}?verify")
        return RedirectResponse(APP)
    return RedirectResponse("/auth/start")


@router.get("/atlassian/callback")
def atlassian_callback(request: Request, code: str | None = None, state: str | None = None,
                       error: str | None = None, db: Session = Depends(get_db)):
    user = signed_in_user(request, db)
    if not user:
        return _fail(request, "Log in first")
    if error or not code:
        return _fail(request, "Atlassian sign in was cancelled")
    if not _state_ok(request, state):
        return _fail(request, "Sign in expired. Please try again")
    try:
        tokens, site = atlassian_exchange(code)
    except HTTPException as exc:
        return _fail(request, str(exc.detail))
    store_atlassian_tokens(user, tokens)
    user.jira_cloud_id = site["id"]
    user.jira_site = site["name"]
    db.commit()
    return RedirectResponse("/auth/start")


def page_redirect_if_signed_in(request: Request, db: Session) -> RedirectResponse | None:
    if signed_in_user(request, db):
        return RedirectResponse(safe_next(request.query_params.get("next"), APP))
    return None
