"""Checks the real database in .env through the real app: creates one temporary account, checks every row it
writes (account, project, specs, collection, two-step), then deletes it. Agent tables must not change.

Run from the repo root:  .venv\Scripts\python.exe -m scripts.check_database
GitHub and Jira are faked, so no webhook is created. Safe to run on the shared Neon database."""
import json, uuid
from unittest import mock
import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from backend.agent_db import agent_tables
from backend.db import Collection, Project, RecoveryCode, SessionLocal, SpecFile, User, engine
from backend.main import app, mark_verified
from backend.security import seal, unseal_totp

assert engine.dialect.name == "postgresql", "DATABASE_URL in .env is not PostgreSQL"
# risk_assessments is this app's own agent table; test_runs, test_results and test_drafts belong to
# the Test Agent and are only checked when they exist. agent_tables() skips the ones that do not.
AGENT = tuple(agent_tables())

def fingerprint():
    with engine.connect() as c:
        return {t: (c.execute(text(f"select count(*) from {t}")).scalar(),
                    c.execute(text(f"select md5(coalesce(string_agg(x::text, '|' order by x::text), '')) from {t} x")).scalar())
                for t in AGENT}

def one(model, **w):
    with SessionLocal() as db:
        return db.scalar(select(model).filter_by(**w))

def n(model, **w):
    with SessionLocal() as db:
        return len(db.scalars(select(model).filter_by(**w)).all())

def ok(cond, label):
    assert cond, label
    print("  ok ", label)

before = fingerprint()
print("agent tables before:", before)
EMAIL, PW, PW2 = f"smoke-{uuid.uuid4().hex[:8]}@example.com", "Neon smoke 42x", "Neon smoke 43y"
SPEC = "import { test, expect } from '@playwright/test';\ntest('%s', async () => { expect(1).toBe(1); });\n"
COL = lambda *r: json.dumps({"info": {"name": "API", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
                             "item": [{"name": x, "request": {"method": "GET", "url": f"http://x/{x}"}} for x in r]})
patches = [mock.patch("backend.api.list_jira_projects", return_value=[{"key": "QA", "name": "QA Board"}]),
           mock.patch("backend.api.ensure_webhook", return_value=111), mock.patch("backend.api.delete_webhook"),
           mock.patch("backend.api.ping_webhook", side_effect=lambda t, repo, h: mark_verified(repo))]
for p in patches: p.start()
uid = None
try:
    with TestClient(app, base_url="https://testserver", follow_redirects=False) as c:
        print("accounts")
        r = c.post("/auth/signup", json={"name": "Smoke Test", "email": EMAIL, "password": PW}); ok(r.status_code == 201, f"signup 201 ({r.status_code})")
        u = one(User, email=EMAIL); uid = u.id
        ok(u.password_hash.startswith("scrypt$") and PW not in u.password_hash, "password stored hashed")
        ok(c.post("/auth/logout").status_code == 204, "logout")
        ok(c.post("/auth/login", json={"email": EMAIL.upper(), "password": PW}).status_code == 200, "login reads the account")
        ok(c.post("/api/account/name", json={"name": "Smoke Renamed"}).status_code == 200 and one(User, id=uid).name == "Smoke Renamed", "rename updates row")
        ok(c.post("/api/account/password", json={"password": PW, "new_password": PW2}).status_code == 200, "password change")
        ok(one(User, id=uid).session_version >= 1, "session_version bumped")
        with SessionLocal() as db:
            x = db.get(User, uid); x.github_token, x.atlassian_token, x.github_login, x.jira_site = seal("gh"), seal("atl"), "smoke", "smoke.atlassian.net"; db.commit()
        print("project and library")
        r = c.post("/api/connect", json={"repo": "smoke/repo", "project_key": "QA"}); ok(r.status_code == 200 and r.json()["delivered"], "connect")
        p = one(Project, user_id=uid); ok(p.repo == "smoke/repo" and p.hook_id == 111 and p.webhook_verified_at, "project row + webhook verified")
        r = c.post("/api/library/apply", json={"specs": [{"name": "a.spec.ts", "text": SPEC % "a"}, {"name": "b.spec.ts", "text": SPEC % "b"}],
                                                 "collection": {"name": "api.json", "text": COL("r1", "r2")}})
        ok(r.status_code == 200, f"import ({r.status_code} {r.text[:120]})")
        ok(n(SpecFile, project_id=p.id) == 2 and one(Collection, project_id=p.id).request_count == 2, "2 specs + collection stored")
        r = c.post("/api/library/apply", json={"specs": [{"name": "a.spec.ts", "text": SPEC % "a2", "revision": 1}]})
        ok(r.status_code == 200 and one(SpecFile, project_id=p.id, name="a.spec.ts").revision == 2, "update bumps revision")
        ok(c.post("/api/library/apply", json={"specs": [{"name": "a.spec.ts", "text": SPEC % "stale", "revision": 1}]}).status_code == 409, "stale update refused")
        for _ in range(8):  # repeated identical queries make psycopg use prepared statements through Neon's pooler
            s = c.get("/api/session").json()
        ok([x["name"] for x in s["specs"]] == ["a.spec.ts", "b.spec.ts"] and "a2" in s["specs"][0]["text"], "session reads it back (x8)")
        ok(c.delete("/api/library/specs/b.spec.ts").status_code == 204 and n(SpecFile, project_id=p.id) == 1, "delete spec")
        ok(c.delete("/api/library/collection").status_code == 204 and n(Collection, project_id=p.id) == 0, "delete collection")
        print("two-step verification")
        secret = c.post("/auth/2fa/setup", json={"password": PW2}).json()["secret"].replace(" ", "")
        r = c.post("/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()}); ok(r.status_code == 200, "2fa enable")
        u = one(User, id=uid); ok(secret not in u.totp_secret and unseal_totp(u.totp_secret) == secret, "secret stored encrypted")
        ok(n(RecoveryCode, user_id=uid) == 10, "10 hashed recovery codes")
        print("delete everything")
        ok(c.post("/api/disconnect").status_code == 204 and n(Project, user_id=uid) == 0 and n(SpecFile, project_id=p.id) == 0, "disconnect removes project + library")
        r = c.post("/api/account/delete", json={"password": PW2, "code": r.json()["recovery_codes"][0]})
        ok(r.status_code == 204, f"account delete ({r.status_code})")
        ok(n(User, id=uid) == 0 and n(RecoveryCode, user_id=uid) == 0, "no rows left for the test account")
        uid = None
finally:
    for p in patches: p.stop()
    if uid:  # a failed step leaves the account behind: remove only what this script made
        with SessionLocal() as db:
            pr = db.scalar(select(Project).where(Project.user_id == uid))
            if pr:
                for m in (SpecFile, Collection): db.query(m).filter_by(project_id=pr.id).delete()
                db.delete(pr)
            db.query(RecoveryCode).filter_by(user_id=uid).delete(); db.query(User).filter_by(id=uid).delete(); db.commit()
        print("cleaned up after failure")
    after = fingerprint()
    print("agent tables after: ", after)
    assert after == before, "AGENT TABLES CHANGED"
    print("agent tables unchanged")
