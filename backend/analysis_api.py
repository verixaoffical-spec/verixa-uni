"""JSON API for the Risk Analysis screen: `/api/analysis`.

Reads the rows the Analysis Agent wrote and, on request, asks it to score a pull request now.
Every route needs an account, through the same `current_user` dependency the rest of the dashboard
uses, so the session cookie and the 401 contract ("the session is gone") are unchanged.
"""
import logging
from importlib.util import find_spec

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent_db import RiskAssessment, to_json
from .analysis_service import AgentUnavailable, analyse_now
from .api import MAX_INT, current_user, project_of
from .auth import _check_origin
from .db import User, get_db

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analysis")

LABELS = ("High", "Medium", "Low")


@router.get("/pull-requests")
def pull_requests(limit: int = Query(50, ge=1, le=200),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Every pull request the agent has looked at for this account's project, newest first.

    No project connected is not an error: the screen shows its own "connect a repository first"
    state, the same way the Test Library does.
    """
    project = project_of(db, user)
    if not project:
        return {"project": None, "items": [], "counts": {}, "agent_available": find_spec("google.adk") is not None}

    # Only the repository connected now: rows from before switching repository are kept, but they are not this screen's.
    mine = (RiskAssessment.project_id == project.id, RiskAssessment.repo == project.repo)
    newest_first = (RiskAssessment.created_at.desc(), RiskAssessment.id.desc())
    rows = db.scalars(select(RiskAssessment).where(*mine).order_by(*newest_first).limit(limit)).all()

    # Counts are over the latest assessment per pull request, so one PR pushed to five times is
    # counted once, at its current risk. They cover every row, whatever the page size.
    latest = {}
    for row in db.execute(select(RiskAssessment.pr_number, RiskAssessment.risk_label, RiskAssessment.state)
                          .where(*mine).order_by(*newest_first)):
        latest.setdefault(row.pr_number, row)
    counts = {label: 0 for label in LABELS}
    for row in latest.values():
        if row.risk_label in counts:
            counts[row.risk_label] += 1

    return {
        "project": {"repo": project.repo, "jira_key": project.jira_key,
                    "webhook_verified": bool(project.webhook_verified_at)},
        "items": [to_json(row) for row in rows],
        "counts": {
            **counts,
            "total": len(latest),
            "pending": sum(1 for r in latest.values() if r.state in ("queued", "running")),
            "needs_review": sum(1 for r in latest.values() if r.state == "needs_human_review"),
            "failed": sum(1 for r in latest.values() if r.state == "failed"),
        },
        "agent_available": find_spec("google.adk") is not None,
    }


@router.get("/pull-requests/{assessment_id}")
def one_assessment(assessment_id: int = Path(ge=1, le=MAX_INT), user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """One assessment in full. 404 for a row that belongs to somebody else, never 403, so the id
    space of another account cannot be probed."""
    project = project_of(db, user)
    row = db.get(RiskAssessment, assessment_id) if project else None
    if not row or not project or row.project_id != project.id:
        raise HTTPException(404, "No analysis with that id")
    return to_json(row)


class AnalyseIn(BaseModel):
    pr_number: int = Field(strict=True, ge=1, le=10_000_000)  # strict: true and "4" are not pull request numbers


@router.post("/analyse")
async def analyse(body: AnalyseIn, request: Request, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """Scores a pull request now, instead of waiting for GitHub to deliver an event.

    This is how a tester re-runs the analysis after a failure, and how the flow is tested without
    a public tunnel. It runs the agent inline and answers when it is done, which takes as long as
    the model chain takes: it is a dashboard call, not a webhook, so there is no 10 second limit.
    """
    _check_origin(request)
    project = project_of(db, user)
    if not project:
        raise HTTPException(409, "Connect a repository first")
    if not user.github_token:
        raise HTTPException(409, "Link GitHub first, so Verixa can read the pull request")

    from .security import unseal
    try:
        token = unseal(user.github_token)
    except Exception:
        raise HTTPException(409, "Your stored GitHub token could not be read. Link GitHub again")

    try:
        row_id = await analyse_now(project, body.pr_number, token)
    except AgentUnavailable as exc:
        raise HTTPException(503, str(exc))
    except ValueError as exc:
        raise HTTPException(502, str(exc))
    except Exception as exc:
        log.exception("on-demand analysis of %s#%s failed", project.repo, body.pr_number)
        raise HTTPException(500, f"The analysis failed: {type(exc).__name__}")

    row = db.get(RiskAssessment, row_id)
    if not row:
        raise HTTPException(500, "The analysis produced no result")
    db.refresh(row)
    return to_json(row)
