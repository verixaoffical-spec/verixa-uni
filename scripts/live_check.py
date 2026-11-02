"""End to end on the real shared database with the real agent: signed webhook -> Analysis Agent
-> risk_assessments on Neon -> GET /api/analysis/pull-requests, then removes everything it made.

Run from the mid folder:  .venv\\Scripts\\python.exe <this file>
"""
import hashlib
import hmac
import json
import os
import sys
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

import backend  # noqa: F401  loads .env
from backend.agent_db import RiskAssessment, init_agent_db
from backend.db import Collection, Project, RecoveryCode, SessionLocal, SpecFile, User, engine
from backend.main import app
from backend.security import seal
from backend.settings import settings

assert engine.dialect.name == "postgresql", "not pointed at PostgreSQL"

PR_REPO = os.getenv("LIVE_REPO", "psf/requests")
PR_NUMBER = int(os.getenv("LIVE_PR_NUMBER", "6500"))
EMAIL = f"e2e-{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = "Crimson harbor 42x"
ok_count, fail_count = 0, 0


def ok(cond, label):
    global ok_count, fail_count
    if cond:
        ok_count += 1
        print("  ok  ", label)
    else:
        fail_count += 1
        print("  FAIL", label)


uid = None
try:
    init_agent_db()
    with TestClient(app, base_url="https://testserver", follow_redirects=False) as c:
        print("setup")
        r = c.post("/auth/signup", json={"name": "Temp Probe", "email": EMAIL, "password": PASSWORD})
        ok(r.status_code == 201, f"temporary account created ({r.status_code})")
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == EMAIL))
            uid = user.id
            # Give it the real GitHub token and a project, as the OAuth flow and /api/connect would.
            user.github_token = seal(os.environ["GITHUB_TOKEN"])
            user.github_login = "e2e"
            db.add(Project(user_id=uid, repo=PR_REPO, jira_key="E2E", jira_name="E2E Board"))
            db.commit()
        print(f"  ok   project connected to {PR_REPO}")

        print(f"\nsigned webhook delivery for {PR_REPO}#{PR_NUMBER}")
        body = json.dumps({
            "action": "opened", "number": PR_NUMBER,
            "pull_request": {"title": "Live end to end check", "html_url": f"https://github.com/{PR_REPO}/pull/{PR_NUMBER}",
                             "head": {"sha": "0" * 40, "ref": "feature"}, "base": {"ref": "main"},
                             "user": {"login": "someone"}},
            "repository": {"full_name": PR_REPO},
        }).encode()
        sig = "sha256=" + hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()

        bad = c.post("/webhooks/github", content=body,
                     headers={"x-github-event": "pull_request", "x-hub-signature-256": "sha256=wrong"})
        ok(bad.status_code == 401, "an unsigned delivery is refused (401)")

        r = c.post("/webhooks/github", content=body,
                   headers={"x-github-event": "pull_request", "x-hub-signature-256": sig,
                            "x-github-delivery": "live-e2e-1", "content-type": "application/json"})
        ok(r.status_code == 202 and r.json() == {"received": "pull_request"}, f"delivery accepted ({r.status_code})")

        print("\nwhat the agent wrote to Neon")
        with SessionLocal() as db:
            rows = db.scalars(select(RiskAssessment).where(RiskAssessment.pr_number == PR_NUMBER)).all()
            row = next((x for x in rows if x.project_id is not None), None)
        ok(row is not None, "a risk_assessments row exists")
        if row:
            ok(row.state in ("scored", "needs_human_review"), f"state = {row.state}")
            ok(row.risk_label in ("Low", "Medium", "High"), f"risk_label = {row.risk_label}")
            ok(isinstance(row.score, int), f"score = {row.score}")
            ok(bool(row.risk_factors), "the rule factor trace was stored")
            print(f"       module={row.module} files={row.files_changed} lines={row.lines_changed} "
                  f"past_defects={row.past_defects} sensitivity={row.sensitivity}")
            if row.state == "scored":
                ok(bool(row.reasoning), "the model wrote the reasoning")
                ok(bool(json.loads(row.test_areas or "[]")), "the model wrote test areas")
                print(f"       model={row.model_used} attempts={row.attempts}")
                print(f"       reasoning: {(row.reasoning or '')[:160]}...")
            else:
                print(f"       escalated after {row.attempts} attempts: {row.errors}")

        print("\nwhat the dashboard reads back")
        r = c.get("/api/analysis/pull-requests")
        ok(r.status_code == 200, f"GET /api/analysis/pull-requests ({r.status_code})")
        feed = r.json()
        ok(feed["project"]["repo"] == PR_REPO, "the feed names the connected repository")
        ok(len(feed["items"]) >= 1, f"{len(feed['items'])} item(s) in the feed")
        if feed["items"]:
            item = feed["items"][0]
            ok(item["risk_label"] == row.risk_label, "the API serves the stored label")
            ok(item["risk_factors"] == json.loads(row.risk_factors), "the factor trace round-trips through JSON")
            ok(feed["counts"].get(item["risk_label"]) == 1, f"counts: {feed['counts']}")
            print(f"       test areas served: {len(item['test_areas'])}")

        print("\ncleanup")
        detail = c.get(f"/api/analysis/pull-requests/{row.id}") if row else None
        ok(detail is not None and detail.status_code == 200, "the single-assessment route works")
        ok(c.post("/api/disconnect").status_code == 204, "disconnect")
        with SessionLocal() as db:
            left = db.scalar(select(RiskAssessment).where(RiskAssessment.id == row.id)) if row else None
        ok(left is None, "disconnect removed the risk assessment")

        r = c.post("/api/account/delete", json={"password": PASSWORD, "code": ""})
        ok(r.status_code == 204, f"account deleted ({r.status_code})")
        uid = None
finally:
    if uid:
        with SessionLocal() as db:
            project = db.scalar(select(Project).where(Project.user_id == uid))
            if project:
                db.query(RiskAssessment).filter_by(project_id=project.id).delete()
                for model in (SpecFile, Collection):
                    db.query(model).filter_by(project_id=project.id).delete()
                db.delete(project)
            db.query(RecoveryCode).filter_by(user_id=uid).delete()
            db.query(User).filter_by(id=uid).delete()
            db.commit()
        print("cleaned up after a failure")

print(f"\n{ok_count} checks passed, {fail_count} failed")
sys.exit(1 if fail_count else 0)

