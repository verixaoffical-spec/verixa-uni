"""Account settings: change the name or password, or delete the account.

Changing the password or deleting the account asks for the password again, like the two-step settings.
Wrong answers return 400, never 401, because the dashboard treats 401 as a session that has ended.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .accounts import hash_password, name_problem, normalize_name, password_problem
from .api import current_user, remove_project
from .auth import _check_origin, _field_error, account_json
from .db import RecoveryCode, User, get_db
from .twofactor import ConfirmIn, _confirm_identity, _counted, _second_factor, _sign_out_other_sessions

router = APIRouter(prefix="/api/account")


class NameIn(BaseModel):
    name: str = Field("", max_length=500)


class PasswordChangeIn(BaseModel):
    password: str = Field("", max_length=500)
    new_password: str = Field("", max_length=500)


@router.post("/name")
def rename(body: NameIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_origin(request)
    name = normalize_name(body.name)
    if problem := name_problem(name):
        raise _field_error("name", problem)
    user.name = name
    db.commit()
    return {"account": account_json(user)}


@router.post("/password")
def change_password(body: PasswordChangeIn, request: Request, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    _check_origin(request)
    if not user.password_hash:
        raise HTTPException(409, "This account signs in with GitHub, so it has no password to change")
    _confirm_identity(request, user, body.password)
    if problem := password_problem(body.new_password, user.email or "", user.name or ""):
        raise _field_error("new_password", problem)
    if body.new_password == body.password:
        raise _field_error("new_password", "Choose a password different from your current one")
    user.password_hash = hash_password(body.new_password)
    _sign_out_other_sessions(request, db, user)  # a stolen session stops working once the password changes
    return {"account": account_json(user)}


@router.post("/delete", status_code=204)
def delete_account(body: ConfirmIn, request: Request, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """Deletes the account with its project, Test Library and recovery codes. With two-step verification on,
    a code is needed too."""
    _check_origin(request)
    _confirm_identity(request, user, body.password)
    if user.totp_secret:
        _counted(request, user, lambda: _second_factor(db, user, body.code))
    remove_project(db, user)
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    db.delete(user)
    db.commit()
    request.session.clear()
    return Response(status_code=204)
