"""JSON API for UC4 to UC11: staging address, runs, results and evidence, drafted tests, tickets, fixes, comparison,
trends and QA Memory.

Every route needs an account and only ever sees the account's own project: an id that belongs to somebody else
answers 404, never 403, so ids cannot be probed. Every change also checks the Origin header (no cross site requests).
"""
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import execution as ex
from . import qa_service as qa
from .accounts import Throttle
from .agent_db import RiskAssessment
from .api import MAX_INT, current_user, project_of
from .auth import _check_origin
from .db import Project, User, get_db
from .memory import entry_json
from .qa_db import DraftTicket, Evidence, FixSuggestion, MemoryEntry, TestDraft, TestResult, TestRun, log_decision
from .settings import settings

router = APIRouter(prefix="/api")
runs_by_user = Throttle(limit=settings.max_runs_per_hour, window=3600)
fixes_by_user = Throttle(limit=30, window=3600)  # each suggestion costs model calls
def Id():
    """A path id: positive and small enough for the database. A new object per route, so FastAPI names each one."""
    return Path(ge=1, le=MAX_INT)


def _project(db: Session, user: User) -> Project:
    project = project_of(db, user)
    if not project:
        raise HTTPException(409, "Connect a repository first")
    return project


def _owned(db: Session, model, row_id: int, project: Project):
    """The row, if it belongs to this project. Results, evidence and fixes are reached through their run."""
    row = db.get(model, row_id)
    run = None
    if isinstance(row, TestRun):
        run = row
    elif isinstance(row, TestResult):
        run = db.get(TestRun, row.run_id)
    elif isinstance(row, (Evidence, FixSuggestion)):
        result = db.get(TestResult, row.result_id)
        run = result and db.get(TestRun, result.run_id)
    elif row is not None and getattr(row, "project_id", None) == project.id:
        return row
    if not row or not run or run.project_id != project.id:
        raise HTTPException(404, "Not found")
    return row


def _limit(throttle: Throttle, user: User, what: str) -> None:
    """Refuses when the account used up its quota. The caller counts the use with throttle.fail once it really starts."""
    if wait := throttle.retry_after(str(user.id)):
        raise HTTPException(429, f"Too many {what}. Try again in {wait // 60 + 1} minute(s)", headers={"Retry-After": str(wait)})


# ---------- staging address ----------

class StagingIn(BaseModel):
    url: str = Field(max_length=500)


@router.post("/project/staging")
def save_staging(body: StagingIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_origin(request)
    project = _project(db, user)
    if problem := ex.staging_problem(body.url):
        raise HTTPException(422, problem)
    project.staging_url = ex.clean_staging(body.url)
    db.commit()
    return {"staging_url": project.staging_url, "reachable": ex.probe(project.staging_url + "/") is not None}


# ---------- runs (UC4, UC6) ----------

class RunIn(BaseModel):
    assessment_id: int = Field(strict=True, ge=1, le=MAX_INT)


@router.post("/runs", status_code=202)
def run_now(body: RunIn, request: Request, background: BackgroundTasks, user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    """Run Now (Req 4.1): the only way a test run starts. It answers at once; progress arrives over the WebSocket."""
    _check_origin(request)
    project = _project(db, user)
    assessment = db.get(RiskAssessment, body.assessment_id)
    if not assessment or assessment.project_id != project.id or assessment.repo != project.repo:
        raise HTTPException(404, "No analysis with that id")
    if assessment.state in ("queued", "running"):
        raise HTTPException(409, "This pull request is still being scored. Run it once it has a risk label")
    _limit(runs_by_user, user, "runs this hour")
    run = qa.start_run(db, user, project, assessment)
    runs_by_user.fail(str(user.id))
    background.add_task(qa.execute_run, run.id)
    return qa.run_json(db, run)


@router.get("/runs")
def list_runs(pr_number: int | None = Query(None, ge=1, le=MAX_INT), limit: int = Query(50, ge=1, le=200),
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_of(db, user)
    if not project:
        return {"items": [], "staging_url": None}
    query = select(TestRun).where(TestRun.project_id == project.id)
    if pr_number:
        query = query.where(TestRun.pr_number == pr_number)
    runs = db.scalars(query.order_by(TestRun.id.desc()).limit(limit)).all()
    return {"items": [qa.run_json(db, r) for r in runs], "staging_url": project.staging_url}


@router.get("/runs/{run_id}")
def one_run(run_id: int = Id(), user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = _project(db, user)
    run = _owned(db, TestRun, run_id, project)
    results = db.scalars(select(TestResult).where(TestResult.run_id == run.id).order_by(TestResult.id)).all()
    ids = [r.id for r in results]
    evidence = db.scalars(select(Evidence).where(Evidence.result_id.in_(ids))).all() if ids else []
    tickets = db.scalars(select(DraftTicket).where(DraftTicket.result_id.in_(ids))).all() if ids else []
    fixes = db.scalars(select(FixSuggestion).where(FixSuggestion.result_id.in_(ids)).order_by(FixSuggestion.id)).all() if ids else []
    drafts = db.scalars(select(TestDraft).where(TestDraft.run_id == run.id)).all()
    return {
        "run": qa.run_json(db, run),
        "results": [qa.result_json(r, [e for e in evidence if e.result_id == r.id]) for r in results],
        "tickets": [qa.ticket_json(db, t) for t in tickets],
        "fixes": [qa.fix_json(f) for f in fixes],
        "drafts": [qa.draft_json(d) for d in drafts],
    }


CONTENT = {"screenshot": ("image/png", "inline"), "trace": ("application/zip", "attachment"),
           "console_log": ("text/plain; charset=utf-8", "inline"), "network_log": ("text/plain; charset=utf-8", "inline")}


@router.get("/evidence/{evidence_id}")
def evidence(evidence_id: int = Id(), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """One proof file (Req 6.2). Only the account's own, and only from inside the evidence folder."""
    project = _project(db, user)
    item = _owned(db, Evidence, evidence_id, project)
    path = ex.evidence_file(item.file_path)
    if not path:
        raise HTTPException(404, "This proof file is no longer available")
    media, disposition = CONTENT.get(item.evidence_type, ("application/octet-stream", "attachment"))
    return FileResponse(path, media_type=media, filename=path.name, content_disposition_type=disposition)


# ---------- drafted tests (UC5) ----------

class DecisionIn(BaseModel):
    approve: bool = Field(strict=True)


@router.get("/drafts")
def list_drafts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_of(db, user)
    if not project:
        return {"items": []}
    drafts = db.scalars(select(TestDraft).where(TestDraft.project_id == project.id).order_by(TestDraft.id.desc()).limit(100))
    return {"items": [qa.draft_json(d) for d in drafts]}


@router.post("/drafts/{draft_id}/decision")
def decide_draft(body: DecisionIn, request: Request, draft_id: int = Id(), user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    _check_origin(request)
    project = _project(db, user)
    return qa.decide_draft(db, user, project, _owned(db, TestDraft, draft_id, project), body.approve)


# ---------- tickets (UC7) ----------

class TicketIn(BaseModel):
    title: str = Field(min_length=5, max_length=250)
    root_cause: str = Field(min_length=10, max_length=5000)
    steps: list[str] = Field(min_length=1, max_length=20)
    priority: Literal["High", "Medium", "Low"]


@router.get("/tickets")
def list_tickets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_of(db, user)
    if not project:
        return {"items": []}
    tickets = db.scalars(select(DraftTicket).where(DraftTicket.project_id == project.id).order_by(DraftTicket.id.desc()).limit(200))
    return {"items": [qa.ticket_json(db, t) for t in tickets]}


@router.post("/tickets/{ticket_id}")
def edit_ticket(body: TicketIn, request: Request, ticket_id: int = Id(), user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    """TBD7: the tester may correct the draft before filing it."""
    _check_origin(request)
    project = _project(db, user)
    ticket = _owned(db, DraftTicket, ticket_id, project)
    if ticket.status != "Drafted":
        raise HTTPException(409, f"This ticket was already {ticket.status.lower()}")
    steps = [s.strip()[:300] for s in body.steps if s.strip()]
    if not steps or not body.title.strip() or not body.root_cause.strip():
        raise HTTPException(422, "Title, likely cause and at least one step are needed")
    ticket.title, ticket.root_cause, ticket.steps, ticket.priority = body.title.strip(), body.root_cause.strip(), "\n".join(steps), body.priority
    db.commit()
    return qa.ticket_json(db, ticket)


@router.post("/tickets/{ticket_id}/file")
async def file_ticket(request: Request, ticket_id: int = Id(), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Approve and file in Jira (Req 7.5): the one place Verixa writes to Jira."""
    _check_origin(request)
    project = _project(db, user)
    ticket = _owned(db, DraftTicket, ticket_id, project)
    return await run_in_threadpool(qa.file_ticket, db, user, project, ticket)


@router.post("/tickets/{ticket_id}/reject")
def reject_ticket(request: Request, ticket_id: int = Id(), user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_origin(request)
    project = _project(db, user)
    return qa.reject_ticket(db, user, project, _owned(db, DraftTicket, ticket_id, project))


# ---------- Suggest a Fix (UC9) ----------

@router.post("/results/{result_id}/fix")
async def suggest_fix(request: Request, result_id: int = Id(), user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_origin(request)
    project = _project(db, user)
    result = _owned(db, TestResult, result_id, project)
    if result.outcome != "real_bug":
        raise HTTPException(409, "A fix can only be suggested for a failure marked as a real bug")
    _limit(fixes_by_user, user, "fix suggestions this hour")
    fixes_by_user.fail(str(user.id))
    return qa.fix_json(await qa.suggest_fix(result.id, user.id))


@router.post("/fixes/{fix_id}/decision")
def decide_fix(body: DecisionIn, request: Request, fix_id: int = Id(), user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    _check_origin(request)
    project = _project(db, user)
    return qa.decide_fix(db, user, project, _owned(db, FixSuggestion, fix_id, project), body.approve)


# ---------- Regression Comparison (UC10) ----------

@router.get("/compare")
def compare(a: int | None = Query(None, ge=1, le=MAX_INT), b: int | None = Query(None, ge=1, le=MAX_INT),
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Compares run a (before) with run b (after). Without ids: the latest finished run and the one before it."""
    project = _project(db, user)
    done = db.scalars(select(TestRun).where(TestRun.project_id == project.id, TestRun.status.in_(("finished", "flagged")))
                      .order_by(TestRun.id.desc())).all()
    if len(done) < 2:
        raise HTTPException(409, "Run the tests at least twice before comparing")
    if a is None and b is None:
        before, after = done[1], done[0]
    elif a is None or b is None or a == b:
        raise HTTPException(422, "Pick two different runs")
    else:
        before, after = _owned(db, TestRun, a, project), _owned(db, TestRun, b, project)
        if before.status not in ("finished", "flagged") or after.status not in ("finished", "flagged"):
            raise HTTPException(409, "Only finished runs can be compared")
    return qa.compare(db, project, before, after)


# ---------- Cross PR Risk Trends (UC11) ----------

@router.get("/trends")
def trends(days: int = Query(30), module: str | None = Query(None, max_length=200),
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    if days not in (7, 30, 90, 365):
        raise HTTPException(422, "Pick a period of 7, 30, 90 or 365 days")
    project = project_of(db, user)
    if not project:
        raise HTTPException(409, "Connect a repository first")
    return qa.trends(db, project, days, module or None)


# ---------- QA Memory (UC8) ----------

@router.get("/memory")
def memory(kind: str | None = Query(None, max_length=20), user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = project_of(db, user)
    if not project:
        return {"items": []}
    query = select(MemoryEntry).where(MemoryEntry.project_id == project.id)
    if kind:
        query = query.where(MemoryEntry.kind == kind)
    return {"items": [entry_json(e) for e in db.scalars(query.order_by(MemoryEntry.id.desc()).limit(300))]}


@router.post("/memory/{entry_id}/delete", status_code=204)
def forget(request: Request, entry_id: int = Id(), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """TBD15: a tester removes a wrong memory entry. It is no longer used by any agent."""
    _check_origin(request)
    project = _project(db, user)
    entry = _owned(db, MemoryEntry, entry_id, project)
    log_decision(db, user.id, project.id, "memory_delete", entry.id, "approved")
    db.delete(entry)
    db.commit()
