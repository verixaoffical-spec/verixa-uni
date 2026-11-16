"""JSON API used by the dashboard: session, connect, and the Test Library."""
import time

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .accounts import Throttle
from .agent_db import RiskAssessment
from .auth import _check_origin, account_json, signed_in_user
from .db import Collection, Project, SpecFile, User, get_db
from .integrations import (
    delete_webhook, ensure_webhook, github_access_token, list_jira_projects, list_repos, ping_webhook, webhook_url,
)
from .library import ApplyError, plan_apply
from .qa_db import delete_project_data
from .validators import MAX_SPECS

router = APIRouter(prefix="/api")
NOT_LINKED = "Connect GitHub and Atlassian first"
MAX_INT = 2 ** 31 - 1  # the largest number the database columns hold
saves_by_user = Throttle(limit=20, window=60)  # checking a full library takes seconds, so one account cannot repeat it


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """401 always means the session is gone, so the dashboard knows to send the person to log in."""
    user = signed_in_user(request, db)
    if not user:
        raise HTTPException(401, "Sign in first")
    return user


def project_of(db: Session, user: User) -> Project | None:
    return db.scalar(select(Project).where(Project.user_id == user.id))


def remove_project(db: Session, user: User) -> None:
    """Removes the webhook, the Test Library and the project. GitHub being unreachable never blocks this."""
    project = db.scalar(select(Project).where(Project.user_id == user.id).with_for_update())
    if not project:
        return
    if project.hook_id and user.github_token:
        try:
            delete_webhook(github_access_token(db, user), project.repo, project.hook_id)
        except (HTTPException, InvalidToken):
            pass
    db.execute(delete(SpecFile).where(SpecFile.project_id == project.id))
    db.execute(delete(Collection).where(Collection.project_id == project.id))
    # The agent's risk assessments point at this project, so they go with it. Without this, both
    # disconnecting and deleting an account would hit a foreign key error.
    db.execute(delete(RiskAssessment).where(RiskAssessment.project_id == project.id))
    delete_project_data(db, project.id)  # runs, evidence rows, drafts, tickets and QA Memory
    db.delete(project)


@router.get("/session")
def session(request: Request, db: Session = Depends(get_db)):
    """Everything the dashboard needs on load, so a refresh never loses state."""
    user = signed_in_user(request, db)
    empty = {"account": None, "github": None, "atlassian": None, "project": None, "specs": [], "collection": None}
    if not user:
        return empty
    project = project_of(db, user)
    out = {
        **empty,
        "account": account_json(user),
        "github": {"login": user.github_login, "name": user.github_name or user.github_login} if user.github_token else None,
        "atlassian": {"site": user.jira_site} if user.atlassian_token else None,
    }
    if project:
        collection = db.scalar(select(Collection).where(Collection.project_id == project.id))
        specs = db.scalars(select(SpecFile).where(SpecFile.project_id == project.id).order_by(SpecFile.name))
        out["project"] = {
            "repo": project.repo, "jira_key": project.jira_key, "jira_name": project.jira_name,
            "webhook_verified": bool(project.webhook_verified_at), "staging_url": project.staging_url,
        }
        out["specs"] = [{"name": s.name, "size": s.size, "text": s.content, "revision": s.revision} for s in specs]
        out["collection"] = collection and {
            "name": collection.name, "size": collection.size, "text": collection.content, "revision": collection.revision,
        }
    return out


@router.get("/targets")
def targets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.github_token or not user.atlassian_token:
        raise HTTPException(403, NOT_LINKED)
    return {"repos": list_repos(github_access_token(db, user)), "projects": list_jira_projects(db, user)}


class ConnectIn(BaseModel):
    repo: str = Field(pattern=r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$", max_length=200)
    project_key: str = Field(min_length=1, max_length=50)

    @field_validator("repo")
    @classmethod
    def not_a_path_trick(cls, repo: str) -> str:
        """The name goes into GitHub API addresses, where ../.. would point at a different API call."""
        if any(not part.strip(".") for part in repo.split("/")):
            raise ValueError("That is not a repository name")
        return repo


def _wait_for_delivery(db: Session, project: Project, tries: int = 8) -> bool:
    """GitHub sends a ping to our webhook right after it is created. Wait a few seconds for it."""
    for _ in range(tries):
        time.sleep(0.75)
        db.refresh(project)
        if project.webhook_verified_at:
            return True
    return False


@router.post("/connect")
def connect(body: ConnectIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_origin(request)
    if not user.github_token or not user.atlassian_token:
        raise HTTPException(403, NOT_LINKED)
    token = github_access_token(db, user)
    jira = next((p for p in list_jira_projects(db, user) if p["key"] == body.project_key), None)
    if not jira:
        raise HTTPException(400, "That Jira project was not found")

    project = project_of(db, user) or Project(user_id=user.id)
    if project.hook_id and project.repo != body.repo:
        delete_webhook(token, project.repo, project.hook_id)  # switching repository removes the old webhook
    project.hook_id = ensure_webhook(token, body.repo)
    project.repo = body.repo
    project.jira_key, project.jira_name = jira["key"], jira["name"]
    project.webhook_verified_at = None
    db.add(project)
    db.commit()

    ping_webhook(token, body.repo, project.hook_id)
    delivered = _wait_for_delivery(db, project)
    label = f"{jira['name']} ({jira['key']})"
    steps = [
        f"Repository access granted for {body.repo}",
        f"Jira project linked: {label}",
        "Webhook created for pull request events",
    ]
    if delivered:
        steps.append("Test delivery received from GitHub")
    return {
        "jira": label,
        "delivered": delivered,
        "steps": steps,
        "warning": None if delivered else (
            f"GitHub could not reach {webhook_url()}. The webhook exists, but PUBLIC_URL must be "
            "a public address that is running (is ngrok still open?). See the README."
        ),
    }


@router.post("/disconnect", status_code=204)
def disconnect(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Disconnecting a project that is already gone succeeds, so a retry is always safe."""
    _check_origin(request)
    remove_project(db, user)
    db.commit()
    return Response(status_code=204)


# ---------- Test Library ----------

class SpecIn(BaseModel):
    name: str = Field(max_length=255)
    text: str = Field(max_length=600_000)
    revision: int | None = Field(default=None, ge=1, le=MAX_INT)  # the revision the dashboard last saw, or None for a new file


class SpecDeleteIn(BaseModel):
    name: str = Field(max_length=255)
    revision: int | None = Field(default=None, ge=1, le=MAX_INT)


class CollectionIn(BaseModel):
    name: str = Field(max_length=255)
    text: str = Field(max_length=5_500_000)
    revision: int | None = Field(default=None, ge=1, le=MAX_INT)


class RevisionIn(BaseModel):
    revision: int | None = Field(default=None, ge=1, le=MAX_INT)


class ApplyIn(BaseModel):
    specs: list[SpecIn] = Field(default_factory=list, max_length=MAX_SPECS)
    delete_specs: list[SpecDeleteIn] = Field(default_factory=list, max_length=MAX_SPECS)
    collection: CollectionIn | None = None
    delete_collection: RevisionIn | None = None


def _apply(db: Session, user: User, body: ApplyIn) -> dict:
    """Saves, updates and deletes in one transaction: either every change lands or none does."""
    # Locking the project row makes two simultaneous saves run one after the other.
    project = db.scalar(select(Project).where(Project.user_id == user.id).with_for_update())
    if not project:
        raise HTTPException(409, "Connect a repository first")

    rows = {s.name: s for s in db.scalars(select(SpecFile).where(SpecFile.project_id == project.id))}
    collection_row = db.scalar(select(Collection).where(Collection.project_id == project.id))
    existing_specs = {n: {"revision": r.revision, "text": r.content} for n, r in rows.items()}
    existing_col = collection_row and {"revision": collection_row.revision, "name": collection_row.name, "text": collection_row.content}

    try:
        plan = plan_apply(existing_specs, existing_col, body.model_dump())
    except ApplyError as exc:
        db.rollback()
        raise HTTPException(exc.status, exc.detail)

    for item in plan["upsert"]:
        row = rows.get(item["name"]) or SpecFile(project_id=project.id, name=item["name"])
        row.content, row.size, row.test_count = item["text"], len(item["text"].encode("utf-8")), item["tests"]
        if item["exists"]:
            row.revision += 1
        db.add(row)
    for name in plan["delete"]:
        db.delete(rows[name])
    if plan["collection"]:
        c = plan["collection"]
        row = collection_row or Collection(project_id=project.id)
        row.name, row.content = c["name"], c["text"]
        row.size, row.request_count = len(c["text"].encode("utf-8")), c["requests"]
        if c["exists"]:
            row.revision += 1
        db.add(row)
    if plan["delete_collection"]:
        db.delete(collection_row)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"conflicts": [{"kind": "library", "name": "", "reason": "changed"}]})
    return plan["summary"]


@router.post("/library/apply")
def apply_library(body: ApplyIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_origin(request)
    if wait := saves_by_user.retry_after(str(user.id)):
        raise HTTPException(429, f"Too many saves in a row. Try again in {wait} seconds", headers={"Retry-After": str(wait)})
    saves_by_user.fail(str(user.id))
    return _apply(db, user, body)


@router.delete("/library/specs/{name}", status_code=204)
def delete_spec(request: Request, name: str = Path(max_length=255), revision: int | None = Query(None, ge=1, le=MAX_INT),
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Deleting a file that is already gone succeeds, so a retry is always safe."""
    _check_origin(request)
    _apply(db, user, ApplyIn(delete_specs=[SpecDeleteIn(name=name, revision=revision)]))
    return Response(status_code=204)


@router.delete("/library/collection", status_code=204)
def delete_collection(request: Request, revision: int | None = Query(None, ge=1, le=MAX_INT),
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_origin(request)
    _apply(db, user, ApplyIn(delete_collection=RevisionIn(revision=revision)))
    return Response(status_code=204)