"""Tables for test runs, evidence, drafted tests, tickets and approvals (UC4 to UC7).

They sit on the same Base as backend/db.py, so init_db() creates them and the tests drop and rebuild them together.
Big proof files (screenshots, traces, logs) stay on the server disk: only their paths are stored here (Req 6.5).
"""
import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, now

# Allowed values, from Appendix B.3 of the SRS
OUTCOMES = ("passed", "real_bug", "temporary_error", "deployment_pending", "skipped")
RUN_STATES = ("running", "finished", "flagged", "failed")
DRAFT_STATES = ("Drafted", "Approved", "Rejected")
TICKET_STATES = ("Drafted", "Filed", "Rejected")


class TestRun(Base):
    __tablename__ = "qa_runs"
    __test__ = False  # a database table, not a test class
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    repo: Mapped[str] = mapped_column(String(200))
    pr_number: Mapped[int]
    head_sha: Mapped[str | None] = mapped_column(String(64))
    risk_label: Mapped[str | None] = mapped_column(String(10))
    module: Mapped[str | None] = mapped_column(String(200))
    triggered_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    staging_url: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="running")
    step: Mapped[str | None] = mapped_column(String(200))     # what the run is doing now, for the screen
    error: Mapped[str | None] = mapped_column(Text)
    selection: Mapped[str | None] = mapped_column(Text)        # JSON: why these tests were chosen
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TestResult(Base):
    __tablename__ = "qa_results"
    __test__ = False
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("qa_runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))              # playwright or newman
    file: Mapped[str] = mapped_column(String(255))             # spec file, or the collection's folder path
    title: Mapped[str] = mapped_column(String(500))
    outcome: Mapped[str] = mapped_column(String(20))
    retried: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(default=0)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("qa_results.id"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(20))     # screenshot, trace, console_log, network_log
    file_path: Mapped[str] = mapped_column(String(500))        # relative to EVIDENCE_DIR
    secrets_redacted: Mapped[bool] = mapped_column(Boolean, default=False)


class TestDraft(Base):
    """A test the Test Agent wrote for changed code no uploaded test covers (UC5). Unused until approved."""
    __tablename__ = "qa_test_drafts"
    __test__ = False
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("qa_runs.id"), index=True)
    module: Mapped[str] = mapped_column(String(200))
    file_name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="Drafted")
    model_used: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DraftTicket(Base):
    """A Jira ticket written by the Report Agent for one real bug. Jira sees it only after the tester approves (UC7)."""
    __tablename__ = "draft_tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("qa_results.id"), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    steps: Mapped[str] = mapped_column(Text)
    root_cause: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10))
    assignee: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(10), default="Drafted")
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)  # the Manager could not accept the agent's text
    model_used: Mapped[str | None] = mapped_column(String(120))
    jira_key: Mapped[str | None] = mapped_column(String(50))
    jira_url: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalLog(Base):
    """Every decision a tester makes: starting a run, a drafted test or a ticket."""
    __tablename__ = "approval_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(20))   # run_start, test_draft, ticket
    target_id: Mapped[int]
    decision: Mapped[str] = mapped_column(String(20))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def log_decision(db: Session, user_id: int, project_id: int, action: str, target: int, decision: str) -> None:
    db.add(ApprovalLog(user_id=user_id, project_id=project_id, action_type=action, target_id=target, decision=decision))


def delete_project_data(db: Session, project_id: int) -> None:
    """Removes everything a project's runs produced, children first, and their evidence files on disk."""
    from .execution import remove_run_files
    remove_run_files(list(db.scalars(select(TestRun.id).where(TestRun.project_id == project_id))))
    run_ids = select(TestRun.id).where(TestRun.project_id == project_id)
    result_ids = select(TestResult.id).where(TestResult.run_id.in_(run_ids))
    for statement in (
        delete(Evidence).where(Evidence.result_id.in_(result_ids)),
        delete(DraftTicket).where(DraftTicket.project_id == project_id),
        delete(TestDraft).where(TestDraft.project_id == project_id),
        delete(TestResult).where(TestResult.run_id.in_(run_ids)),
        delete(TestRun).where(TestRun.project_id == project_id),
        delete(ApprovalLog).where(ApprovalLog.project_id == project_id),
    ):
        db.execute(statement)


def loads(raw: str | None, fallback=None):
    try:
        return json.loads(raw) if raw else fallback
    except ValueError:
        return fallback
