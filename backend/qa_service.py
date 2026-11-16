"""Runs, tickets and drafted tests (UC4 to UC7). The routes in qa_api.py call these.

One run, start to end (Figure 2 of the SRS):
  Run Now -> pick tests -> check staging -> Playwright and Newman together -> sort every result -> save the proof
  -> Report Agent drafts a ticket for each real bug -> Test Agent drafts tests for
  changed modules no test covers. The Manager checks each agent's work and retries up to AGENT_MAX_ATTEMPTS.
Nothing reaches Jira here: a ticket is filed only by file_ticket, after the tester approves it.
"""
import asyncio
import json
import logging
import re
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from agents import report
from agents.redact import hide_secrets
from agents.risk_rules import module_of
from agents.supervisor import supervise
from agents.trace import mask, trace

from . import execution as ex
from .agent_db import RiskAssessment
from .db import Collection, Project, SessionLocal, SpecFile, User, now
from .integrations import github_access_token
from .jira import describe, file_issue
from .qa_db import (
    DraftTicket, Evidence, TestDraft, TestResult, TestRun, loads, log_decision,
)
from .settings import settings
from .validators import validate_spec

log = logging.getLogger(__name__)
FAILED = ("real_bug", "temporary_error")
PRIORITY = {"High": "High", "Medium": "Medium", "Low": "Low"}
MAX_DRAFTS_PER_RUN = 3     # coverage gap drafts per run, so one huge pull request cannot use the whole model budget
MAX_EXPLAINED_PER_RUN = 10  # real bugs the Report Agent explains per run; the rest still get a ticket draft


def step(run: TestRun, text: str, level: str = "info", done: bool = False, first: bool = False) -> None:
    """One line of live progress for the dashboard (Req 4.9), through the same trace log the Analysis Agent uses."""
    trace("qa.start" if first else "qa.step", f"{run.repo}#{run.pr_number}", test_run=run.id, text=text, level=level,
          done=done)


# ---------- choosing tests (Req 4.2) ----------

def select_tests(specs: dict[str, str], label: str | None, modules: list[str]) -> tuple[list[str], str]:
    """Which specs fit this pull request, and why. High risk runs everything (the full regression set)."""
    everything = sorted(specs)
    words = {m.lower() for m in modules if m and m != "root" and len(m) >= 3}
    if label == "High":
        return everything, "High risk, so the full regression set runs"
    if not words:
        return everything, "No changed module is known, so every spec runs"
    chosen = {name for name, text in specs.items()
              if any(w in name.lower() or any(w in t.lower() for t in ex.spec_titles(text)) for w in words)}
    if not chosen:
        return everything, f"No spec mentions {', '.join(sorted(words))}, so every spec runs to be safe"
    return sorted(chosen), f"Specs about {', '.join(sorted(words))}"


def covered(module: str, specs: dict[str, str], collection_text: str | None) -> bool:
    """A module counts as covered when a spec's name or a test title, or the collection, mentions it (Req 5.1)."""
    word = module.lower()
    if any(word in name.lower() or any(word in t.lower() for t in ex.spec_titles(text)) for name, text in specs.items()):
        return True
    return bool(collection_text) and word in collection_text.lower()


# ---------- starting a run (UC4) ----------

def start_run(db: Session, user: User, project: Project, assessment: RiskAssessment) -> TestRun:
    if not project.staging_url:
        raise HTTPException(409, "Add the staging address on Integrations first. Tests never run on the live system")
    if problem := ex.staging_problem(project.staging_url):
        raise HTTPException(409, f"The staging address cannot be used: {problem}")
    if problem := ex.tools_ready():
        raise HTTPException(503, problem)
    has_specs = db.scalar(select(SpecFile.id).where(SpecFile.project_id == project.id).limit(1))
    has_collection = db.scalar(select(Collection.id).where(Collection.project_id == project.id))
    if not has_specs and not has_collection:
        raise HTTPException(409, "The Test Library is empty. Upload Playwright specs or a Postman collection first")
    busy = db.scalar(select(TestRun.id).where(TestRun.project_id == project.id, TestRun.status == "running"))
    if busy:
        raise HTTPException(409, "A run is already in progress for this project. Wait for it to finish")
    run = TestRun(project_id=project.id, repo=project.repo, pr_number=assessment.pr_number, head_sha=assessment.head_sha,
                  risk_label=assessment.risk_label, module=assessment.module, triggered_by=user.id,
                  staging_url=ex.clean_staging(project.staging_url), status="running", step="Starting",
                  selection=json.dumps({"modules": loads(assessment.modules_touched, []) or
                                                   ([assessment.module] if assessment.module else []), "author": assessment.author}))
    db.add(run)
    db.flush()
    log_decision(db, user.id, project.id, "run_start", run.id, "approved")
    db.commit()
    return run


def recover_runs() -> None:
    """A run cannot outlive the server. At start up, runs left running by a restart are marked failed."""
    with SessionLocal() as db:
        for run in db.scalars(select(TestRun).where(TestRun.status == "running")):
            run.status, run.error, run.ended_at = "failed", "The server restarted during this run. Start it again", now()
        db.commit()


def _changed_code(user_id: int, repo: str, pr_number: int) -> list[dict]:
    """The pull request's changed files with their patches, secrets hidden. [] when GitHub cannot be read."""
    from agents.github_client import fetch_pr
    try:
        with SessionLocal() as db:
            user = db.get(User, user_id)
            token = github_access_token(db, user) if user and user.github_token else None
        _, files = fetch_pr(repo, pr_number, token)
        return [{"file": f["filename"], "module": module_of(f["filename"])[0],
                 "patch": hide_secrets(f.get("patch") or "")[0][:4000]} for f in files]
    except Exception as exc:
        log.info("could not read the changed code of %s#%s: %s", repo, pr_number, mask(str(exc))[:200])
        return []


def _code_for(files: list[dict], module: str | None = None) -> str:
    chosen = [f for f in files if not module or f["module"] == module] or files
    return "\n\n".join(f"{f['file']}\n{f['patch']}" for f in chosen[:8])


async def execute_run(run_id: int) -> None:
    """The background job behind Run Now. Never raises: whatever happens is written onto the run."""
    with SessionLocal() as db:
        run = db.get(TestRun, run_id)
        if not run:
            return
        specs = {s.name: s.content for s in db.scalars(select(SpecFile).where(SpecFile.project_id == run.project_id))}
        col = db.scalar(select(Collection).where(Collection.project_id == run.project_id))
        collection = (col.name, col.content) if col else None
        info = loads(run.selection, {})
    gave_up = False
    try:
        step(run, f"Test Agent started for PR #{run.pr_number}", first=True)
        chosen, reason = select_tests(specs, run.risk_label, info.get("modules") or [])
        _update(run_id, step="Checking staging", selection=json.dumps({**info, "specs": chosen, "reason": reason,
                                                                       "collection": collection[0] if collection else None}))
        step(run, f"Test Agent picked {len(chosen)} spec(s){' and the Postman collection' if collection else ''}: {reason}")

        to_run, pending = await asyncio.to_thread(ex.deployment_check, run.staging_url, {n: specs[n] for n in chosen})
        if pending:
            step(run, f"{len(pending)} spec(s) are not on staging yet and are marked deployment pending", "warn")

        _update(run_id, step="Running tests on staging")
        step(run, "Playwright and Newman are running on staging")
        folder = ex.workspace(run_id)

        async def work(_feedback):
            results = []
            jobs = []
            if to_run:
                ex.write_playwright(folder, run.staging_url, {n: specs[n] for n in to_run})
                jobs.append(asyncio.to_thread(ex.run_playwright, folder))
            if collection:
                jobs.append(asyncio.to_thread(ex.run_newman, folder, run.staging_url, collection[1]))
            reports = await asyncio.gather(*jobs)  # both tools at the same time (Req 4.3)
            if to_run:
                results += ex.playwright_results(reports.pop(0))
            if collection:
                api = ex.newman_results(reports[0], collection[0])
                if any(r["outcome"] == "temporary_error" for r in api):
                    second = await asyncio.to_thread(ex.run_newman, folder, run.staging_url, collection[1], "newman2.json")
                    api = ex.merge_newman_retry(api, ex.newman_results(second, collection[0]))
                results += api
            return results

        def check(results) -> list[str]:
            if not isinstance(results, list):
                return ["no results"]
            if (to_run or collection) and not results:
                return ["the tools ran but reported no tests"]
            if any(r.get("outcome") not in ("passed", "real_bug", "temporary_error", "deployment_pending", "skipped")
                   or not r.get("title") for r in results):
                return ["a result has no title or an unknown outcome"]
            return []

        if to_run or collection:
            results, _, problems = await supervise("test", work, check, f"{run.repo}#{run.pr_number}")
            if results is None:
                raise ex.RunError("The tests could not be run: " + "; ".join(problems)[:500])
        else:
            results = []
        for name, why in pending.items():
            for title in ex.spec_titles(specs[name]) or ["(whole file)"]:
                results.append({"kind": "playwright", "file": name, "title": title, "outcome": "deployment_pending",
                                "retried": False, "error": why, "ms": 0, "attachments": {}})

        ids = await asyncio.to_thread(_save_results, run_id, folder, results)
        counts = {o: sum(1 for r in results if r["outcome"] == o) for o in ("passed", "real_bug", "temporary_error", "deployment_pending", "skipped")}
        step(run, f"Results: {counts['passed']} passed, {counts['real_bug']} real bug(s), {counts['temporary_error']} "
                  f"temporary error(s), {counts['deployment_pending']} pending", "warn" if counts["real_bug"] else "ok")

        bugs = [i for i, r in zip(ids, results) if r["outcome"] == "real_bug"]
        files = await asyncio.to_thread(_changed_code, run.triggered_by, run.repo, run.pr_number) if bugs or run.module else []
        if bugs:
            _update(run_id, step="Report Agent is drafting tickets")
            step(run, f"Report Agent is writing {len(bugs)} ticket draft(s). Nothing goes to Jira until you approve")
            for n, result_id in enumerate(bugs):
                gave_up |= not await draft_ticket(result_id, files, explain=n < MAX_EXPLAINED_PER_RUN)

        _update(run_id, step="Looking for coverage gaps")
        gave_up |= not await draft_gap_tests(run_id, specs, collection[1] if collection else None, files)
        status = "flagged" if gave_up else "finished"
        _update(run_id, status=status, step="Done", ended_at=now())
        step(run, "Run finished. Some agent work needs a human review" if gave_up else "Run finished",
             "warn" if gave_up else "ok", done=True)
    except ex.RunError as exc:
        _update(run_id, status="failed", error=str(exc), step="Stopped", ended_at=now())
        step(run, str(exc), "error", done=True)
    except Exception as exc:
        log.exception("test run %s crashed", run_id)
        _update(run_id, status="failed", error=f"The run stopped because of an error ({type(exc).__name__})",
                step="Stopped", ended_at=now())
        step(run, "The run stopped because of an error", "error", done=True)
    finally:
        import shutil
        shutil.rmtree(ex.RUNNER / "runs" / f"run_{int(run_id)}", ignore_errors=True)


def _update(run_id: int, **fields) -> None:
    with SessionLocal() as db:
        run = db.get(TestRun, run_id)
        if run:
            for key, value in fields.items():
                setattr(run, key, value)
            db.commit()


def _save_results(run_id: int, folder, results: list[dict]) -> list[int]:
    """Stores every result, and the proof of each failure."""
    ids = []
    with SessionLocal() as db:
        run = db.get(TestRun, run_id)
        for r in results:
            row = TestResult(run_id=run_id, kind=r["kind"], file=r["file"][:255], title=r["title"][:500],
                             outcome=r["outcome"], retried=bool(r.get("retried")),
                             error_message=hide_secrets(r.get("error") or "")[0][:4000] or None, duration_ms=int(r.get("ms") or 0))
            db.add(row)
            db.flush()
            ids.append(row.id)
            if r["outcome"] in FAILED:
                for kind, path in ex.save_evidence(run_id, row.id, folder, r):
                    db.add(Evidence(result_id=row.id, evidence_type=kind, file_path=path, secrets_redacted=kind.endswith("_log")))
        db.commit()
    return ids


# ---------- the Report Agent: ticket drafts (UC7) ----------

async def draft_ticket(result_id: int, files: list[dict], explain: bool = True) -> bool:
    """Writes the draft for one real bug. Returns False when the Manager had to flag it for a person."""
    with SessionLocal() as db:
        result = db.get(TestResult, result_id)
        run = db.get(TestRun, result.run_id)
        if db.scalar(select(DraftTicket.id).where(DraftTicket.result_id == result_id)):
            return True
        # The same test failing again on the same pull request already has an open or filed ticket: no duplicate
        earlier = db.scalar(select(DraftTicket.id).join(TestResult, TestResult.id == DraftTicket.result_id)
                            .join(TestRun, TestRun.id == TestResult.run_id).where(
            TestRun.project_id == run.project_id, TestRun.pr_number == run.pr_number, TestResult.kind == result.kind,
            TestResult.file == result.file, TestResult.title == result.title, DraftTicket.status.in_(("Drafted", "Filed"))))
        if earlier:
            return True
        evidence = db.scalars(select(Evidence).where(Evidence.result_id == result_id, Evidence.evidence_type.in_(("console_log", "network_log")))).all()
        logs = ""
        for e in evidence:
            path = ex.evidence_file(e.file_path)
            logs += (path.read_text(encoding="utf-8", errors="replace")[:1500] + "\n") if path else ""
        author = loads(run.selection, {}).get("author")
        title, error = result.title, result.error_message or ""

    answer, problems = None, ["not explained, the per run limit was reached"]
    if explain:
        answer, _, problems = await supervise(
            "report", lambda fb: report.explain_failure(title, error, logs, _code_for(files, run.module), fb),
            lambda a: report.check_explanation(a, title, error), f"{run.repo}#{run.pr_number}")
    first_line = (error.strip().splitlines() or ["see the attached logs"])[0][:200]
    steps = (answer or {}).get("steps") or [f"Open the staging app at {run.staging_url}",
                                            f"Run the test \"{title}\" from {result.file}", f"See it fail: {first_line}"]
    with SessionLocal() as db:
        db.add(DraftTicket(
            project_id=run.project_id, result_id=result_id,
            title=f"[{run.module or 'app'}] {title} fails on PR #{run.pr_number}"[:250],
            steps="\n".join(s.strip() for s in steps),
            root_cause=(answer or {}).get("likely_cause") or
                       "The Report Agent could not explain this failure, so read the error and logs before filing. "
                       f"Reason: {'; '.join(problems)[:300]}",
            priority=PRIORITY.get(run.risk_label or "", "Medium"), assignee=author,
            flagged=answer is None,
            model_used=(answer or {}).get("model")))
        db.commit()
    return answer is not None or not explain


# ---------- the Test Agent: drafts for coverage gaps (UC5) ----------

def _draft_name(module: str, taken: set[str]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", module.lower()).strip("-")[:60] or "module"
    name, n = f"verixa-{slug}.spec.ts", 2
    while name.lower() in taken:
        name, n = f"verixa-{slug}-{n}.spec.ts", n + 1
    return name


async def draft_gap_tests(run_id: int, specs: dict[str, str], collection_text: str | None, files: list[dict]) -> bool:
    """Drafts a test for each changed module nothing covers. Returns False when the Manager flagged one."""
    with SessionLocal() as db:
        run = db.get(TestRun, run_id)
        modules = [m for m in loads(run.selection, {}).get("modules") or [] if m and m != "root"]
        waiting = {d.module for d in db.scalars(select(TestDraft).where(TestDraft.project_id == run.project_id, TestDraft.status == "Drafted"))}
        taken = {n.lower() for n in specs} | {d.file_name.lower() for d in db.scalars(select(TestDraft).where(TestDraft.project_id == run.project_id))}
    gaps = [m for m in modules if not covered(m, specs, collection_text) and m not in waiting][:MAX_DRAFTS_PER_RUN]
    if not gaps:
        step(run, "Every changed module already has a test, so nothing was drafted", "ok")
        return True
    ok = True
    for module in gaps:
        code = _code_for(files, module)
        name = _draft_name(module, taken)
        taken.add(name.lower())
        step(run, f"Test Agent is drafting {name}: no test covers {module}")
        answer, _, problems = await supervise(
            "test_draft", lambda fb: report.draft_test(module, code or f"(changes in {module})", name, fb),
            lambda a: report.check_draft(a, module, validate_spec), f"{run.repo}#{run.pr_number}")
        if answer is None:
            ok = False
            step(run, f"The drafted test for {module} was not good enough after every attempt. It needs a person", "warn")
            continue
        with SessionLocal() as db:
            db.add(TestDraft(project_id=run.project_id, run_id=run_id, module=module[:200], file_name=name,
                             code=answer["code"], model_used=answer.get("model")))
            db.commit()
        step(run, f"Drafted {name}. It waits for your approval", "ok")
    return ok


def decide_draft(db: Session, user: User, project: Project, draft: TestDraft, approve: bool) -> dict:
    if draft.status != "Drafted":
        raise HTTPException(409, f"This draft was already {draft.status.lower()}")
    if approve:
        result = validate_spec(draft.file_name, draft.code)  # the library's own rules, again, before it is stored
        if result["errors"]:
            raise HTTPException(422, "The drafted test breaks a library rule: " + "; ".join(result["errors"]))
        if db.scalar(select(SpecFile.id).where(SpecFile.project_id == project.id, SpecFile.name == draft.file_name)):
            raise HTTPException(409, f"A spec named {draft.file_name} is already in the library")
        db.add(SpecFile(project_id=project.id, name=draft.file_name, content=draft.code,
                        size=len(draft.code.encode("utf-8")), test_count=len(result["tests"])))
    draft.status = "Approved" if approve else "Rejected"
    log_decision(db, user.id, project.id, "test_draft", draft.id, draft.status.lower())
    db.commit()
    return draft_json(draft)


# ---------- filing (UC7) ----------

def file_ticket(db: Session, user: User, project: Project, ticket: DraftTicket) -> dict:
    if ticket.status != "Drafted":
        raise HTTPException(409, f"This ticket was already {ticket.status.lower()}")
    if not user.atlassian_token:
        raise HTTPException(409, "Link Atlassian first")
    result = db.get(TestResult, ticket.result_id)
    run = db.get(TestRun, result.run_id)
    # The raw trace records every request the browser made, passwords included, so it never leaves Verixa (Req 7.3)
    proofs = [p for e in db.scalars(select(Evidence).where(Evidence.result_id == result.id, Evidence.evidence_type != "trace"))
              if (p := ex.evidence_file(e.file_path))]
    try:
        key, url, problems = file_issue(db, user, project.jira_key, hide_secrets(ticket.title)[0],
                                        describe(ticket, result.title, result.error_message or "", f"PR #{run.pr_number}", run.risk_label),
                                        ticket.priority, proofs)
    except HTTPException as exc:
        ticket.error = str(exc.detail)[:500]
        db.commit()
        raise
    ticket.status, ticket.jira_key, ticket.jira_url, ticket.filed_at = "Filed", key, url, now()
    ticket.error = "; ".join(problems) or None
    log_decision(db, user.id, project.id, "ticket", ticket.id, "approved")
    db.commit()
    return ticket_json(db, ticket)


def reject_ticket(db: Session, user: User, project: Project, ticket: DraftTicket) -> dict:
    if ticket.status != "Drafted":
        raise HTTPException(409, f"This ticket was already {ticket.status.lower()}")
    ticket.status = "Rejected"
    log_decision(db, user.id, project.id, "ticket", ticket.id, "rejected")
    db.commit()
    return ticket_json(db, ticket)


# ---------- JSON for the dashboard ----------

def _iso(at):
    from .agent_db import _iso as iso
    return iso(at)


def run_json(db: Session, run: TestRun) -> dict:
    rows = db.execute(select(TestResult.outcome, TestResult.retried).where(TestResult.run_id == run.id)).all()
    counts = {o: sum(1 for r in rows if r.outcome == o) for o in ("passed", "real_bug", "temporary_error", "deployment_pending", "skipped")}
    starter = db.get(User, run.triggered_by)
    return {"id": run.id, "pr_number": run.pr_number, "head_sha": run.head_sha, "risk_label": run.risk_label,
            "module": run.module, "status": run.status, "step": run.step, "error": run.error,
            "staging_url": run.staging_url, "selection": loads(run.selection, {}),
            "started_by": starter.name or starter.github_login if starter else None,
            "started_at": _iso(run.started_at), "ended_at": _iso(run.ended_at),
            "counts": {**counts, "total": len(rows), "retried": sum(1 for r in rows if r.retried)}}


def result_json(r: TestResult, evidence: list[Evidence]) -> dict:
    return {"id": r.id, "kind": r.kind, "file": r.file, "title": r.title, "outcome": r.outcome, "retried": r.retried,
            "error": r.error_message, "ms": r.duration_ms,
            "evidence": [{"id": e.id, "type": e.evidence_type} for e in evidence]}


def draft_json(d: TestDraft) -> dict:
    return {"id": d.id, "run_id": d.run_id, "module": d.module, "file_name": d.file_name, "code": d.code,
            "status": d.status, "model_used": d.model_used, "created_at": _iso(d.created_at)}


def ticket_json(db: Session, t: DraftTicket) -> dict:
    result = db.get(TestResult, t.result_id)
    return {"id": t.id, "result_id": t.result_id, "run_id": result.run_id if result else None,
            "test": result.title if result else None, "title": t.title, "steps": t.steps.splitlines(),
            "root_cause": t.root_cause, "priority": t.priority, "assignee": t.assignee,
            "status": t.status, "flagged": t.flagged, "jira_key": t.jira_key, "jira_url": t.jira_url, "error": t.error,
            "model_used": t.model_used, "created_at": _iso(t.created_at), "filed_at": _iso(t.filed_at)}
