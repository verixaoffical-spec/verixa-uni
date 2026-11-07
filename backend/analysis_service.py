"""The bridge between the webhook, the Analysis Agent and the database.

This is the integration layer the consolidation is about. It is deliberately a plain Python
module: the webhook handler calls `analyse_pull_request` in a background task, which calls the
agent through a direct function call. There is no HTTP hop between the API and the agent, because
both run inside this one FastAPI process.

Flow
    POST /webhooks/github  (signature checked first, answers 202 immediately)
      -> background task: analyse_pull_request(payload, delivery_id)
         -> one risk_assessments row per connected project, state "queued"
         -> agents.runner.run_manager(pr_id, token)      direct call, no HTTP
            -> Analysis Manager (T-035): validate, retry with feedback, cap at 3, escalate
               -> Analysis Agent (T-031/T-033): rules decide the label, one model call explains it
         -> the result is written back onto the row, state "scored" or "needs_human_review"
      -> the dashboard reads it from GET /api/analysis/pull-requests
"""
import asyncio
import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agents.trace import mask, trace

from .agent_db import RiskAssessment, dump
from .db import Project, SessionLocal, User
from .security import unseal

log = logging.getLogger(__name__)

# Only these actions mean "the code changed, score it again". Everything else is ignored.
HANDLED_ACTIONS = {"opened", "synchronize", "reopened"}
GITHUB_URL = "https://github.com/"
SHA_RE = re.compile(r"[0-9a-fA-F]{7,64}")

# `opened` and `synchronize` can arrive together. One analysis per pull request at a time.
_LOCKS: dict[str, asyncio.Lock] = {}


class AgentUnavailable(RuntimeError):
    """google-adk / litellm are not installed, or the agent package failed to import."""


def _load_runner():
    """Imported late and on purpose. The agent pulls in google-adk and litellm, which are heavy and
    may be missing; the dashboard, auth and the Test Library must still work without them."""
    try:
        from agents.runner import run_manager
    except Exception as exc:  # ImportError, or a provider SDK blowing up at import time
        raise AgentUnavailable(f"Analysis Agent is unavailable: {type(exc).__name__}: {exc}") from exc
    return run_manager


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value, limit: int) -> str | None:
    """A cleaned string from a payload, or None. PostgreSQL refuses a NUL character in text."""
    return (value.replace("\x00", "").strip()[:limit] or None) if isinstance(value, str) else None


def pr_facts(payload: dict) -> dict | None:
    """Pulls the fields the agent and the dashboard need out of a `pull_request` event.
    Returns None when the payload is not a usable pull request event."""
    pr = _dict(payload.get("pull_request"))
    repo = _text(_dict(payload.get("repository")).get("full_name"), 200)
    number = payload.get("number") or pr.get("number")
    head = _text(_dict(pr.get("head")).get("sha"), 64)
    if not repo or type(number) is not int or number < 1 or not head or not SHA_RE.fullmatch(head):
        return None
    url = _text(pr.get("html_url"), 500)
    return {
        "repo": repo,
        "pr_number": number,
        "head_sha": head,
        "title": _text(pr.get("title"), 500),
        "pr_url": url if url and url.startswith(GITHUB_URL) else None,  # the screen makes this a link, so never javascript:
        "author": _text(_dict(pr.get("user")).get("login"), 100),
    }


def claim(db: Session, project_id: int, facts: dict, delivery_id: str | None) -> RiskAssessment | None:
    """Takes the row for this (project, pull request, head commit), creating it if needed.

    Returns None when there is nothing to do: GitHub can deliver the same event twice, and a push
    that does not change the head commit should not be scored twice. A row left in `running` by a
    crashed process is retried, and a `failed` row is retried too.
    """
    row = db.scalar(
        select(RiskAssessment).where(
            RiskAssessment.project_id == project_id,
            RiskAssessment.pr_number == facts["pr_number"],
            RiskAssessment.head_sha == facts["head_sha"],
        )
    )
    if row and row.state in ("scored", "needs_human_review"):
        log.info("skipping %s#%s %s: already %s", facts["repo"], facts["pr_number"], facts["head_sha"][:7], row.state)
        return None
    if row is None:
        row = RiskAssessment(project_id=project_id, **facts)
        db.add(row)
    else:  # retry: refresh the facts, in case the title or author changed
        for key, value in facts.items():
            setattr(row, key, value)
    row.delivery_id = (delivery_id or "")[:100] or None
    row.state = "running"
    row.errors = None
    try:
        db.commit()
    except IntegrityError:
        # Another worker inserted the same row between the select and the commit. It owns the work.
        db.rollback()
        return None
    db.refresh(row)
    return row


def store_result(db: Session, row_id: int, result: dict, facts: dict | None) -> None:
    """Writes the agent's output onto the row. `facts` is score_pr's rule output."""
    row = db.get(RiskAssessment, row_id)
    if row is None:  # the account disconnected or was deleted while the agent was working
        log.info("risk row %s disappeared while the agent was running", row_id)
        return

    # GitHub only ever serves the newest commit, so a push during the run means the agent read a later commit than
    # the one this row was created for. The row must describe what was really read.
    requested_sha, read_sha = row.head_sha, (facts or {}).get("head_sha")
    if read_sha and read_sha != requested_sha:
        scored_elsewhere = db.scalar(select(RiskAssessment.id).where(
            RiskAssessment.project_id == row.project_id, RiskAssessment.pr_number == row.pr_number,
            RiskAssessment.head_sha == read_sha, RiskAssessment.id != row.id))
        trace("service.commit_moved", f"{row.repo}#{row.pr_number}", row_id=row_id, requested_sha=requested_sha,
              read_sha=read_sha, already_has_a_row=bool(scored_elsewhere))
        if scored_elsewhere:  # the newer commit has its own row, so this older commit can never be scored now
            row.state = "failed"
            row.errors = dump([f"Commit {requested_sha[:7]} was replaced by {read_sha[:7]} before it could be scored. "
                               f"See the row for {read_sha[:7]}."])
            db.commit()
            return
        row.head_sha = read_sha

    analysis = result.get("analysis") or {}
    if facts:
        row.risk_label = facts.get("risk_label")
        row.base_label = facts.get("base_label")
        row.score = facts.get("score")
        row.module = (facts.get("module") or "")[:200] or None
        row.modules_touched = dump(facts.get("modules_touched") or [])
        row.files_changed = facts.get("files_changed")
        row.lines_changed = facts.get("lines_changed")
        row.past_defects = facts.get("past_defects_in_module")
        row.sensitivity = facts.get("sensitivity")
        row.scoring_basis = (facts.get("scoring_basis") or "")[:200] or None
        row.risk_factors = dump(facts.get("risk_factors") or [])
    elif result.get("risk_label"):
        # escalated before the model step, so the rules still produced a label
        row.risk_label = result.get("risk_label")
        row.risk_factors = dump(result.get("risk_factors") or [])

    # With no accepted answer these are emptied, so a rerun never shows the explanation of an earlier run.
    row.reasoning = analysis.get("reasoning")
    row.test_areas = dump(analysis.get("suggested_test_areas") or [])
    row.model_used = (analysis.get("model") or "")[:120] or None
    row.concern = (analysis.get("concern") or "")[:400] or None  # emptied too, like the explanation

    row.attempts = result.get("attempts") or 0
    errors = [mask(error) for error in result.get("errors") or []]  # a provider's error text can quote a key
    row.errors = dump(errors) if errors else None
    row.state = "scored" if result.get("status") == "approved" else "needs_human_review"
    db.commit()
    log.info("risk row %s -> %s (%s)", row_id, row.state, row.risk_label)
    trace("service.saved", f"{row.repo}#{row.pr_number}", result_of_run=result.get("run_id"), row_id=row_id, state=row.state,
          risk_label=row.risk_label, head_sha_of_row=row.head_sha, head_sha_read=read_sha, head_sha_requested=requested_sha,
          same_commit=None if not read_sha else read_sha == row.head_sha)


def mark_failed(row_id: int, message: str) -> None:
    with SessionLocal() as db:
        row = db.get(RiskAssessment, row_id)
        if row:
            row.state = "failed"
            row.errors = dump([mask(message)[:500]])
            db.commit()
            trace("service.failed", f"{row.repo}#{row.pr_number}", row_id=row_id, head_sha_of_row=row.head_sha, error=message[:300])


async def _score_one(row_id: int, pr_id: str, token: str | None) -> None:
    """Runs the manager -> Analysis Agent loop for one row and saves whatever comes back."""
    try:
        run_manager = _load_runner()
    except AgentUnavailable as exc:
        log.warning("%s", exc)
        mark_failed(row_id, str(exc))
        return

    try:
        from agents.analysis import _CACHE
        _CACHE.pop(pr_id, None)  # the agent reuses this between its retries, but a new push has a new diff
        result = await run_manager(pr_id, token)
    except Exception as exc:
        log.exception("Analysis Agent crashed on %s", pr_id)
        mark_failed(row_id, f"{type(exc).__name__}: {exc}")
        return

    # The agent caches the rule output under the pr_id; read it back so the row keeps the numbers.
    try:
        from agents.analysis import ANALYSES
        facts = (ANALYSES.get(pr_id) or {}).get("facts")
    except Exception:
        facts = None

    try:
        with SessionLocal() as db:
            store_result(db, row_id, result, facts)
    except Exception as exc:
        log.exception("could not save the analysis for %s", pr_id)
        mark_failed(row_id, f"Saving the result failed: {type(exc).__name__}: {exc}")


async def analyse_pull_request(payload: dict, delivery_id: str | None = None) -> None:
    """The webhook's background task. Never raises: a failure is recorded on the row instead."""
    facts = pr_facts(payload)
    if not facts:
        log.info("pull_request event without the fields we need, ignored")
        return
    pr_id = f"{facts['repo']}#{facts['pr_number']}"
    trace("service.delivery", pr_id, delivery_id=delivery_id, head_sha=facts["head_sha"], action=payload.get("action"))

    async with _LOCKS.setdefault(pr_id, asyncio.Lock()):
        # A repository can belong to several accounts (projects.repo is not unique), and each one
        # has its own Jira project and its own GitHub token, so each gets its own row.
        jobs: list[tuple[int, str | None]] = []
        with SessionLocal() as db:
            projects = db.scalars(select(Project).where(Project.repo == facts["repo"])).all()
            if not projects:
                log.info("no connected project for %s, ignored", facts["repo"])
                return
            for project in projects:
                row = claim(db, project.id, facts, delivery_id)
                if row is None:
                    trace("service.skipped", pr_id, project_id=project.id, head_sha=facts["head_sha"], reason="already handled")
                    continue
                user = db.get(User, project.user_id)
                token = None
                if user and user.github_token:
                    try:
                        token = unseal(user.github_token)
                    except Exception:
                        log.warning("could not decrypt the GitHub token of user %s", project.user_id)
                jobs.append((row.id, token))

        for row_id, token in jobs:
            await _score_one(row_id, pr_id, token)


async def analyse_now(project: Project, pr_number: int, token: str | None) -> int | None:
    """Scores a pull request on demand, for the dashboard's "Analyse" button and for testing
    without waiting for GitHub to deliver an event. Returns the row id, or None if nothing ran."""
    pr_id = f"{project.repo}#{pr_number}"
    try:
        run_manager = _load_runner()
    except AgentUnavailable:
        raise

    # The head commit is not known yet, so the agent fetches the pull request first and the row is
    # keyed on the sha it actually read.
    from agents.analysis import ANALYSES, score_pr

    scored = await asyncio.to_thread(score_pr, pr_id, True, token)
    if scored.get("status") != "ok":
        raise ValueError(scored.get("message") or "Could not read the pull request from GitHub")

    facts = {
        "repo": project.repo,
        "pr_number": pr_number,
        "head_sha": (scored.get("head_sha") or "")[:64],
        "title": (scored.get("title") or "")[:500] or None,
        "pr_url": f"https://github.com/{project.repo}/pull/{pr_number}",
        "author": None,
    }
    async with _LOCKS.setdefault(pr_id, asyncio.Lock()):
        with SessionLocal() as db:
            row = db.scalar(
                select(RiskAssessment).where(
                    RiskAssessment.project_id == project.id,
                    RiskAssessment.pr_number == pr_number,
                    RiskAssessment.head_sha == facts["head_sha"],
                )
            )
            if row is None:
                row = RiskAssessment(project_id=project.id, **facts)
                db.add(row)
            else:
                for key, value in facts.items():
                    if value is not None or key != "author":
                        setattr(row, key, value)
            row.state = "running"
            row.errors = None
            db.commit()
            db.refresh(row)
            row_id = row.id

        try:
            result = await run_manager(pr_id, token)
            agent_facts = (ANALYSES.get(pr_id) or {}).get("facts") or scored
            with SessionLocal() as db:
                store_result(db, row_id, result, agent_facts)
        except Exception as exc:  # otherwise the row says "running" forever and the screen never stops polling
            mark_failed(row_id, f"The analysis could not finish: {type(exc).__name__}")
            raise
    return row_id


# ---------- CI finishing after the pull request was scored ----------

RANK = {"Low": 0, "Medium": 1, "High": 2}
CI_RAISE = "raised to High after CI finished: the build or tests fail on this commit"


def _ci_rows(repo: str, sha: str) -> list[tuple[int, str, int, str | None]]:
    """(row id, pr_id, pr number, decrypted token) for every saved assessment of this commit."""
    found = []
    with SessionLocal() as db:
        rows = db.scalars(select(RiskAssessment).where(RiskAssessment.repo == repo, RiskAssessment.head_sha == sha,
                                                       RiskAssessment.state.in_(("scored", "needs_human_review")))).all()
        for row in rows:
            project = db.get(Project, row.project_id)
            user = db.get(User, project.user_id) if project else None
            token = None
            if user and user.github_token:
                try:
                    token = unseal(user.github_token)
                except Exception:
                    log.warning("could not decrypt the GitHub token of user %s", user.id)
            found.append((row.id, f"{repo}#{row.pr_number}", row.pr_number, token))
    return found


def apply_ci(row_id: int, ci: dict) -> dict | None:
    """Writes a CI result onto a saved row: the ci line of the factor trace, and High when CI fails.
    The label is only ever raised here, never lowered. Returns what changed, or None if the row is gone."""
    from agents.risk_rules import ci_factor

    with SessionLocal() as db:
        row = db.get(RiskAssessment, row_id)
        if row is None:
            return None
        factors = [f for f in _list(row.risk_factors) if not f.startswith("ci:") and f != CI_RAISE]
        line = ci_factor(ci)
        at = next((i for i, f in enumerate(factors) if f.startswith("score ")), len(factors))
        if line:
            factors.insert(at, line)
        raised = ci.get("state") == "failure" and RANK.get(row.risk_label or "", -1) < RANK["High"]
        if raised:
            row.risk_label = "High"
            factors.append(CI_RAISE)
        row.risk_factors = dump(factors)
        db.commit()
        return {"risk_label": row.risk_label, "raised": raised}


def _list(raw: str | None) -> list:
    try:
        value = json.loads(raw) if raw else []
    except ValueError:
        return []
    return value if isinstance(value, list) else []


async def apply_check_suite(payload: dict) -> None:
    """GitHub's check_suite event: CI finished on a commit. CI usually starts at the same moment as the pull
    request, so the first score often saw it still running. The full result is read again (one suite can pass
    while another fails) and written onto every saved assessment of that commit. Never raises."""
    try:
        from agents.github_client import ci_status

        suite = _dict(payload.get("check_suite"))
        repo = _text(_dict(payload.get("repository")).get("full_name"), 200)
        sha = _text(suite.get("head_sha"), 64)
        if payload.get("action") != "completed" or not repo or not sha or not SHA_RE.fullmatch(sha):
            return
        for row_id, pr_id, _, token in await asyncio.to_thread(_ci_rows, repo, sha):
            try:
                ci = await asyncio.to_thread(ci_status, repo, sha, token)
            except Exception as exc:
                trace("ci.read_failed", pr_id, row_id=row_id, error=str(exc)[:300])
                continue
            changed = await asyncio.to_thread(apply_ci, row_id, ci)
            if changed:
                trace("ci.updated", pr_id, row_id=row_id, state=ci["state"], failed=ci["failed"],
                      risk_label=changed["risk_label"], raised=changed["raised"])
    except Exception:
        log.exception("could not apply a check_suite event")
