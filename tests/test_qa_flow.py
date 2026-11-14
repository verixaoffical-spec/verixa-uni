"""Integration tests for UC4 to UC11 through the real app and database. Playwright, Newman, GitHub, Jira and the
model are faked; everything else (routes, ownership, the Manager's checks, QA Memory, the stored rows) is real.

Run:  .\\.venv\\Scripts\\python.exe -m unittest tests.test_qa_flow
"""
import json
import tempfile
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from sqlalchemy import select

from backend import execution as ex
from backend import qa_api
from backend.agent_db import AgentBase, RiskAssessment, init_agent_db
from backend.db import Project, SessionLocal, SpecFile, engine
from backend.qa_db import ApprovalLog, DraftTicket, Evidence, MemoryEntry, TestDraft, TestResult, TestRun

from .test_crud import CrudTestCase, count, row, spec

STAGING = "http://127.0.0.1:4010"
EXPLAIN = {"likely_cause": "The cart total adds the item price twice, so the cart total test sees 30 instead of 20.",
           "steps": ["Open the cart", "Add two notebooks", "Read the total"]}
DRAFT = ("import { test, expect } from '@playwright/test';\n"
         "test('wishlist page lists saved items', async ({ page }) => { await page.goto('/wishlist');"
         " await expect(page.getByRole('heading')).toBeVisible(); });\n")
FIX = {"diff": "--- a/src/cart/total.js\n+++ b/src/cart/total.js\n@@ -1 +1 @@\n-return a + a\n+return a\n",
       "explanation": "The total added the price twice. Returning the single price fixes the cart total test."}
PATCHES = [{"filename": "src/cart/total.js", "additions": 1, "deletions": 1, "patch": "@@ -1 +1 @@\n-return a\n+return a + a"},
           {"filename": "src/wishlist/page.js", "additions": 5, "deletions": 0, "patch": "+export const page = 1"}]


def pw_report(*tests):
    """A Playwright JSON report. tests: (title, status, error)."""
    return {"suites": [{"title": "cart.spec.ts", "file": "cart.spec.ts", "specs": [
        {"title": t, "file": "cart.spec.ts", "tests": [{"status": s, "results": [{"duration": 3, "error": {"message": e} if e else None}] * (2 if e else 1)}]}
        for t, s, e in tests]}]}


def nm_report(*requests):
    """A Newman JSON report. requests: (name, response code, failed assertion or None)."""
    return {"collection": {"item": [{"id": n, "name": n} for n, _, _ in requests]}, "run": {"executions": [
        {"item": {"id": n, "name": n}, "request": {"method": "GET", "url": {"protocol": "http", "host": ["127.0.0.1"], "port": "4010", "path": [n]}},
         "response": {"code": c, "responseTime": 4}, "assertions": [{"assertion": a, "error": {"message": "expected 200"}}] if a else []}
        for n, c, a in requests]}}


class QaTestCase(CrudTestCase):
    def setUp(self):
        super().setUp()
        AgentBase.metadata.drop_all(engine)
        init_agent_db()
        for t in (qa_api.runs_by_user, qa_api.fixes_by_user):
            t._fails.clear()
        self.evidence = Path(tempfile.mkdtemp())
        self.pw = pw_report(("cart total is right", "unexpected", "expect(received).toBe(expected)\nExpected: 20\nReceived: 30"),
                            ("cart opens", "expected", None))
        self.nm = nm_report(("health", 200, None))
        self.model = {"report": EXPLAIN, "draft_test": {"code": DRAFT}}
        fakes = {
            "tools": mock.patch.object(ex, "tools_ready", return_value=None),
            "evidence": mock.patch.object(ex, "EVIDENCE", self.evidence),
            "probe": mock.patch.object(ex, "probe", return_value=200),
            "pw": mock.patch.object(ex, "run_playwright", side_effect=lambda folder: self.pw),
            "nm": mock.patch.object(ex, "run_newman", side_effect=lambda *a: self.nm),
            "fetch_pr": mock.patch("agents.github_client.fetch_pr", return_value=({}, PATCHES)),
            "explain": mock.patch("agents.report.explain_failure", side_effect=self.fake_explain),
            "draft": mock.patch("agents.report.draft_test", side_effect=self.fake_draft),
            "fix": mock.patch("agents.report.suggest_fix", side_effect=self.fake_fix),
            "github_token": mock.patch("backend.qa_service.github_access_token", return_value="gh"),
        }
        self.patchers = fakes
        self.fake = {k: p.start() for k, p in fakes.items()}

    async def fake_explain(self, *args):
        answer = self.model["report"]
        if isinstance(answer, Exception):
            raise answer
        return {**answer, "model": "fake/report"}

    async def fake_draft(self, *args):
        return {**self.model["draft_test"], "model": "fake/draft"}

    async def fake_fix(self, *args):
        return {**self.model.get("fix", FIX), "model": "fake/fix"}

    # ---- helpers ----

    def ready(self, email="ada@example.com", client=None, modules=("cart", "wishlist"), label="Medium"):
        """A connected account with a staging address, a Test Library and one scored pull request."""
        client = client or self.client
        uid = self.connected_user(email, client=client)
        self.assertEqual(client.post("/api/project/staging", json={"url": STAGING}).status_code, 200)
        res = self.apply(client, specs=[{"name": "cart.spec.ts", "text": spec("cart total is right")}],
                         collection={"name": "api.json", "text": json.dumps({"info": {"name": "API", "schema":
                                     "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
                                     "item": [{"name": "health", "request": {"method": "GET", "url": "{{baseUrl}}/health"}}]})})
        self.assertEqual(res.status_code, 200, res.text)
        with SessionLocal() as db:
            project = db.scalar(select(Project).where(Project.user_id == uid))
            assessment = RiskAssessment(project_id=project.id, repo=project.repo, pr_number=7, head_sha="a" * 40,
                                        state="scored", risk_label=label, module=modules[0] if modules else None,
                                        modules_touched=json.dumps(list(modules)), author="octocat", title="Fix cart")
            db.add(assessment)
            db.commit()
            return assessment.id

    def start(self, assessment_id, client=None):
        res = (client or self.client).post("/api/runs", json={"assessment_id": assessment_id})
        self.assertEqual(res.status_code, 202, res.text)
        return (client or self.client).get(f"/api/runs/{res.json()['id']}").json()


class RunNowTests(QaTestCase):
    def test_happy_path_runs_sorts_drafts_and_remembers(self):
        detail = self.start(self.ready())
        run = detail["run"]
        self.assertEqual(run["status"], "finished", run)
        self.assertEqual(run["counts"]["passed"], 2)
        self.assertEqual(run["counts"]["real_bug"], 1)
        self.assertEqual(run["started_by"], "Ada Lovelace")
        self.assertEqual(run["selection"]["specs"], ["cart.spec.ts"])
        self.assertTrue(self.fake["pw"].called and self.fake["nm"].called)
        bug = next(r for r in detail["results"] if r["outcome"] == "real_bug")
        self.assertEqual({e["type"] for e in bug["evidence"]}, {"console_log"})
        # Report Agent: one draft for the one real bug, nothing filed
        [ticket] = detail["tickets"]
        self.assertEqual((ticket["status"], ticket["priority"], ticket["assignee"], ticket["flagged"]),
                         ("Drafted", "Medium", "octocat", False))
        self.assertEqual(ticket["root_cause"], EXPLAIN["likely_cause"])
        # Test Agent: cart is covered by cart.spec.ts, wishlist is not, so one draft
        [draft] = detail["drafts"]
        self.assertEqual((draft["module"], draft["file_name"], draft["status"]), ("wishlist", "verixa-wishlist.spec.ts", "Drafted"))
        # QA Memory got the real bug, and the run start is in the approval log
        self.assertEqual(count(MemoryEntry, kind="real_bug"), 1)
        self.assertEqual(count(ApprovalLog, action_type="run_start"), 1)

    def test_refusals(self):
        aid = self.ready()
        other = self.new_client()
        other_aid = self.ready("bea@example.com", client=other)
        cases = [({"assessment_id": other_aid}, 404), ({"assessment_id": 999999}, 404), ({"assessment_id": "1"}, 422),
                 ({"assessment_id": 0}, 422), ({"assessment_id": True}, 422), ({}, 422), ({"assessment_id": 2 ** 40}, 422)]
        for body, status in cases:
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/api/runs", json=body).status_code, status)
        self.assertEqual(self.client.post("/api/runs", json={"assessment_id": aid},
                                          headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.new_client().post("/api/runs", json={"assessment_id": aid}).status_code, 401)
        self.assertEqual(count(TestRun), 0)

    def test_without_staging_or_tests_or_while_scoring_nothing_runs(self):
        aid = self.ready()
        with SessionLocal() as db:
            project = db.scalar(select(Project))
            project.staging_url = None
            db.commit()
        res = self.client.post("/api/runs", json={"assessment_id": aid})
        self.assertEqual(res.status_code, 409)
        self.assertIn("staging", res.json()["detail"])
        self.client.post("/api/project/staging", json={"url": STAGING})
        with SessionLocal() as db:
            db.get(RiskAssessment, aid).state = "running"
            db.commit()
        self.assertEqual(self.client.post("/api/runs", json={"assessment_id": aid}).status_code, 409)
        with SessionLocal() as db:
            db.get(RiskAssessment, aid).state = "scored"
            for s in db.scalars(select(SpecFile)):
                db.delete(s)
            db.commit()
        self.apply(delete_collection={"revision": 1})
        res = self.client.post("/api/runs", json={"assessment_id": aid})
        self.assertEqual(res.status_code, 409)
        self.assertIn("empty", res.json()["detail"])
        self.fake["tools"].return_value = "Test tools are not installed"
        self.assertEqual(self.client.post("/api/runs", json={"assessment_id": aid}).status_code, 503)
        self.assertEqual(count(TestRun), 0)

    def test_one_run_at_a_time_and_a_quota(self):
        aid = self.ready()
        with SessionLocal() as db:
            run = TestRun(project_id=db.scalar(select(Project.id)), repo="ada/shop", pr_number=7, triggered_by=1,
                          staging_url=STAGING, status="running")
            db.add(run)
            db.commit()
        self.assertEqual(self.client.post("/api/runs", json={"assessment_id": aid}).status_code, 409)
        with SessionLocal() as db:
            db.scalar(select(TestRun)).status = "failed"
            db.commit()
        with mock.patch.object(qa_api.runs_by_user, "limit", 1):
            self.assertEqual(self.client.post("/api/runs", json={"assessment_id": aid}).status_code, 202)
            res = self.client.post("/api/runs", json={"assessment_id": aid})
            self.assertEqual(res.status_code, 429)
            self.assertIn("Retry-After", res.headers)

    def test_staging_down_fails_the_run_with_a_reason(self):
        self.fake["probe"].return_value = None
        aid = self.ready()
        run = self.start(aid)["run"]
        self.assertEqual(run["status"], "failed")
        self.assertIn("not answering", run["error"])
        self.assertFalse(self.fake["pw"].called)

    def test_undeployed_pages_are_pending_never_failed(self):
        self.fake["probe"].side_effect = lambda url: 404 if url.endswith("/wishlist") else 200
        uid_aid = self.ready()
        self.apply(specs=[{"name": "wish.spec.ts", "text": spec("wishlist").replace("goto('/')", "goto('/wishlist')")
                          if "goto" in spec("wishlist") else spec("wishlist")}])
        with SessionLocal() as db:
            db.add(SpecFile(project_id=db.scalar(select(Project.id)), name="wishlist.spec.ts", size=1, test_count=1,
                            content="import { test, expect } from '@playwright/test';\n"
                                    "test('wishlist shows items', async ({ page }) => { await page.goto('/wishlist'); expect(1).toBe(1); });\n"))
            db.commit()
        detail = self.start(uid_aid)
        pending = [r for r in detail["results"] if r["outcome"] == "deployment_pending"]
        self.assertEqual([p["title"] for p in pending], ["wishlist shows items"])
        self.assertIn("404", pending[0]["error"])
        self.assertEqual(detail["run"]["counts"]["deployment_pending"], 1)

    def test_temporary_errors_get_no_ticket(self):
        self.pw = pw_report(("slow page", "unexpected", "Test timeout of 30000ms exceeded."))
        detail = self.start(self.ready())
        self.assertEqual([r["outcome"] for r in detail["results"] if r["kind"] == "playwright"], ["temporary_error"])
        self.assertTrue(detail["results"][0]["retried"])
        self.assertEqual(detail["tickets"], [])

    def test_a_model_that_never_answers_flags_the_run_but_still_drafts_a_ticket(self):
        self.model["report"] = RuntimeError("all models failed")
        detail = self.start(self.ready(modules=("cart",)))
        self.assertEqual(detail["run"]["status"], "flagged")
        [ticket] = detail["tickets"]
        self.assertTrue(ticket["flagged"])
        self.assertIn("could not explain", ticket["root_cause"])
        self.assertEqual(self.fake["explain"].call_count, 3)  # the Manager's retry limit

    def test_a_bad_draft_is_rejected_by_the_manager_and_never_stored(self):
        self.model["draft_test"] = {"code": "import fs from 'fs';\n" + DRAFT}
        detail = self.start(self.ready())
        self.assertEqual(detail["drafts"], [])
        self.assertEqual(detail["run"]["status"], "flagged")
        self.assertEqual(self.fake["draft"].call_count, 3)

    def test_tool_crash_is_retried_then_the_run_fails(self):
        self.fake["pw"].side_effect = ex.RunError("Playwright did not produce a report")
        run = self.start(self.ready())["run"]
        self.assertEqual(run["status"], "failed")
        self.assertEqual(self.fake["pw"].call_count, 3)

    def test_a_restart_marks_running_runs_failed(self):
        from backend.qa_service import recover_runs
        self.ready()
        with SessionLocal() as db:
            db.add(TestRun(project_id=db.scalar(select(Project.id)), repo="r/r", pr_number=1, triggered_by=1,
                           staging_url=STAGING, status="running"))
            db.commit()
        recover_runs()
        self.assertEqual(row(TestRun).status, "failed")


class StagingTests(QaTestCase):
    def test_staging_address_rules(self):
        self.connected_user()
        for url, status in (("ftp://x", 422), ("http://169.254.169.254", 422), ("javascript:alert(1)", 422), ("", 422),
                            ("http://a:b@x.com", 422), ("x" * 501, 422), (STAGING + "/", 200)):
            with self.subTest(url=url):
                self.assertEqual(self.client.post("/api/project/staging", json={"url": url}).status_code, status)
        self.assertEqual(self.client.post("/api/project/staging", json={"url": 5}).status_code, 422)
        self.assertEqual(self.session()["project"]["staging_url"], STAGING)
        self.assertEqual(self.client.post("/api/project/staging", json={"url": STAGING},
                                          headers={"Origin": "http://evil.example"}).status_code, 403)

    def test_without_a_project_it_is_refused(self):
        self.linked_user()
        self.assertEqual(self.client.post("/api/project/staging", json={"url": STAGING}).status_code, 409)


class EvidenceAndOwnershipTests(QaTestCase):
    def test_evidence_is_served_only_to_its_owner(self):
        detail = self.start(self.ready())
        bug = next(r for r in detail["results"] if r["outcome"] == "real_bug")
        evidence_id = bug["evidence"][0]["id"]
        res = self.client.get(f"/api/evidence/{evidence_id}")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.headers["content-type"].startswith("text/plain"))
        self.assertIn("Received: 30", res.text)
        other = self.new_client()
        self.connected_user("bea@example.com", client=other)
        for path in (f"/api/evidence/{evidence_id}", f"/api/runs/{detail['run']['id']}"):
            self.assertEqual(other.get(path).status_code, 404, path)
        ticket = detail["tickets"][0]
        for path in (f"/api/tickets/{ticket['id']}/file", f"/api/tickets/{ticket['id']}/reject",
                     f"/api/results/{bug['id']}/fix", f"/api/drafts/{detail['drafts'][0]['id']}/decision",
                     f"/api/memory/{row(MemoryEntry).id}/delete"):
            self.assertEqual(other.post(path, json={"approve": True}).status_code, 404, path)
        self.assertEqual(other.get("/api/tickets").json()["items"], [])
        self.assertEqual(other.get("/api/memory").json()["items"], [])

    def test_missing_or_tampered_evidence(self):
        detail = self.start(self.ready())
        bug = next(r for r in detail["results"] if r["outcome"] == "real_bug")
        with SessionLocal() as db:
            ev = db.get(Evidence, bug["evidence"][0]["id"])
            ev.file_path = "../../.env"
            db.commit()
        self.assertEqual(self.client.get(f"/api/evidence/{ev.id}").status_code, 404)
        for bad in ("0", "-1", "abc", str(2 ** 40)):
            self.assertEqual(self.client.get(f"/api/evidence/{bad}").status_code, 422, bad)
        self.assertEqual(self.client.get("/api/evidence/99999").status_code, 404)

    def test_disconnect_removes_every_run_row_and_file(self):
        self.start(self.ready())
        self.assertTrue(any(self.evidence.rglob("*.txt")))
        self.assertEqual(self.client.post("/api/disconnect").status_code, 204)
        for model in (TestRun, TestResult, Evidence, DraftTicket, TestDraft, MemoryEntry, ApprovalLog):
            self.assertEqual(count(model), 0, model.__name__)
        self.assertFalse(any(self.evidence.rglob("*.txt")))


class DraftDecisionTests(QaTestCase):
    def test_approve_adds_it_to_the_library_once(self):
        draft = self.start(self.ready())["drafts"][0]
        url = f"/api/drafts/{draft['id']}/decision"
        for body in ({}, {"approve": "yes"}, {"approve": 1}):
            self.assertEqual(self.client.post(url, json=body).status_code, 422, body)
        res = self.client.post(url, json={"approve": True})
        self.assertEqual(res.json()["status"], "Approved")
        self.assertIsNotNone(row(SpecFile, name="verixa-wishlist.spec.ts"))
        self.assertEqual(self.client.post(url, json={"approve": False}).status_code, 409)
        self.assertEqual(count(ApprovalLog, action_type="test_draft"), 1)
        self.assertEqual(count(MemoryEntry, kind="test_draft"), 1)

    def test_reject_never_touches_the_library(self):
        draft = self.start(self.ready())["drafts"][0]
        self.assertEqual(self.client.post(f"/api/drafts/{draft['id']}/decision", json={"approve": False}).json()["status"], "Rejected")
        self.assertIsNone(row(SpecFile, name="verixa-wishlist.spec.ts"))

    def test_a_draft_edited_in_the_database_to_break_the_rules_cannot_be_approved(self):
        draft = self.start(self.ready())["drafts"][0]
        with SessionLocal() as db:
            db.get(TestDraft, draft["id"]).code = DRAFT + "\nrequire('child_process')"
            db.commit()
        self.assertEqual(self.client.post(f"/api/drafts/{draft['id']}/decision", json={"approve": True}).status_code, 422)
        self.assertIsNone(row(SpecFile, name="verixa-wishlist.spec.ts"))


class TicketTests(QaTestCase):
    def ticket(self):
        return self.start(self.ready())["tickets"][0]

    def test_nothing_reaches_jira_until_approved_then_once(self):
        ticket = self.ticket()
        with mock.patch("backend.qa_service.file_issue", return_value=("QA-12", "https://ada.atlassian.net/browse/QA-12", [])) as jira:
            self.assertFalse(jira.called)
            res = self.client.post(f"/api/tickets/{ticket['id']}/file")
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual((res.json()["status"], res.json()["jira_key"]), ("Filed", "QA-12"))
            args = jira.call_args.args
            self.assertEqual((args[2], args[5]), ("QA", "Medium"))
            self.assertTrue(all(p.name == "console_log.txt" for p in args[6]))
            self.assertEqual(self.client.post(f"/api/tickets/{ticket['id']}/file").status_code, 409)
            self.assertEqual(jira.call_count, 1)
        self.assertEqual(count(ApprovalLog, action_type="ticket", decision="approved"), 1)

    def test_the_same_bug_on_the_same_pull_request_gets_one_ticket(self):
        aid = self.ready()
        self.start(aid)
        self.start(aid)
        self.assertEqual(count(DraftTicket), 1)
        self.client.post(f"/api/tickets/{row(DraftTicket).id}/reject")
        self.start(aid)  # a rejected ticket does not stop a new draft when the bug is still there
        self.assertEqual(count(DraftTicket, status="Drafted"), 1)

    def test_jira_failing_keeps_the_draft_and_says_why(self):
        ticket = self.ticket()
        with mock.patch("backend.qa_service.file_issue", side_effect=HTTPException(502, "Creating the Jira ticket failed (400)")):
            res = self.client.post(f"/api/tickets/{ticket['id']}/file")
        self.assertEqual(res.status_code, 502)
        saved = row(DraftTicket)
        self.assertEqual((saved.status, saved.jira_key), ("Drafted", None))
        self.assertIn("400", saved.error)

    def test_reject_and_edit(self):
        ticket = self.ticket()
        url = f"/api/tickets/{ticket['id']}"
        good = {"title": "Cart total doubles", "root_cause": "The price is added twice.", "steps": ["Open cart", " "], "priority": "High"}
        for body in ({**good, "priority": "Urgent"}, {**good, "title": "abc"}, {**good, "steps": []}, {**good, "steps": [" "]},
                     {**good, "root_cause": "short"}, {**good, "title": "x" * 300}, {**good, "steps": ["a"] * 21}):
            with self.subTest(body=body):
                self.assertEqual(self.client.post(url, json=body).status_code, 422)
        res = self.client.post(url, json=good)
        self.assertEqual((res.json()["title"], res.json()["steps"], res.json()["priority"]), ("Cart total doubles", ["Open cart"], "High"))
        self.assertEqual(self.client.post(url + "/reject").json()["status"], "Rejected")
        self.assertEqual(self.client.post(url, json=good).status_code, 409)
        self.assertEqual(self.client.post(url + "/file").status_code, 409)


class FixTests(QaTestCase):
    def bug(self):
        detail = self.start(self.ready())
        return next(r for r in detail["results"] if r["outcome"] == "real_bug"), detail

    def test_a_fix_is_text_only_and_added_to_the_draft_on_request(self):
        bug, detail = self.bug()
        res = self.client.post(f"/api/results/{bug['id']}/fix")
        self.assertEqual(res.status_code, 200, res.text)
        fix = res.json()
        self.assertEqual(fix["status"], "Suggested")
        self.assertIsNone(row(DraftTicket).fix_text)
        res = self.client.post(f"/api/fixes/{fix['id']}/decision", json={"approve": True})
        self.assertEqual(res.json()["status"], "Added")
        self.assertIn("return a\n", row(DraftTicket).fix_text)
        self.assertEqual(self.client.post(f"/api/fixes/{fix['id']}/decision", json={"approve": False}).status_code, 409)

    def test_only_real_bugs_and_only_usable_fixes(self):
        bug, detail = self.bug()
        passed = next(r for r in detail["results"] if r["outcome"] == "passed")
        self.assertEqual(self.client.post(f"/api/results/{passed['id']}/fix").status_code, 409)
        self.model["fix"] = {"diff": "change it", "explanation": "x"}
        res = self.client.post(f"/api/results/{bug['id']}/fix")
        self.assertEqual(res.status_code, 502)
        self.assertIn("ticket draft is not affected", res.json()["detail"])
        self.assertEqual(row(DraftTicket).status, "Drafted")
        self.fake["fetch_pr"].side_effect = RuntimeError("GitHub down")
        self.assertEqual(self.client.post(f"/api/results/{bug['id']}/fix").status_code, 502)


class CompareAndTrendTests(QaTestCase):
    def test_compare_tags_every_test_and_changes_nothing(self):
        aid = self.ready()
        self.assertEqual(self.client.get("/api/compare").status_code, 409)  # one run is not enough
        first = self.start(aid)["run"]["id"]
        self.pw = pw_report(("cart total is right", "expected", None), ("cart opens", "unexpected", "boom"),
                            ("new one", "expected", None))
        second = self.start(aid)["run"]["id"]
        before = [(r.id, r.outcome) for r in SessionLocal().scalars(select(TestResult))]
        res = self.client.get("/api/compare").json()
        tags = {r["title"]: r["tag"] for r in res["rows"]}
        self.assertEqual(tags, {"cart total is right": "fixed", "cart opens": "new failure", "new one": "new test",
                                "health": "still passing"})
        self.assertEqual((res["a"]["id"], res["b"]["id"]), (first, second))
        self.assertEqual(before, [(r.id, r.outcome) for r in SessionLocal().scalars(select(TestResult))])
        for query, status in (("?a=1", 422), (f"?a={first}&b={first}", 422), (f"?a={first}&b=99999", 404), ("?a=x&b=2", 422)):
            self.assertEqual(self.client.get("/api/compare" + query).status_code, status, query)

    def test_trends_count_only_the_newest_score(self):
        self.ready(label="Low")
        with SessionLocal() as db:
            pid = db.scalar(select(Project.id))
            for n, label in ((7, "High"), (8, "Medium"), (9, "High")):  # PR 7 scored again: High replaces Low
                db.add(RiskAssessment(project_id=pid, repo="ada/shop", pr_number=n, head_sha=str(n) * 40, state="scored",
                                      risk_label=label, module="cart", modules_touched='["cart"]'))
            db.commit()
        res = self.client.get("/api/trends?days=30").json()
        self.assertEqual((res["total"], res["share"], res["enough"]), (3, {"Low": 0, "Medium": 1, "High": 2}, True))
        self.assertEqual(self.client.get("/api/trends?days=30&module=nothing").json()["total"], 0)
        for bad in ("?days=5", "?days=abc", "?module=" + "x" * 201):
            self.assertEqual(self.client.get("/api/trends" + bad).status_code, 422, bad)

    def test_too_little_data_says_so(self):
        self.ready()
        res = self.client.get("/api/trends").json()
        self.assertFalse(res["enough"])


class MemoryTests(QaTestCase):
    def test_memory_lists_finds_and_forgets(self):
        self.start(self.ready())
        items = self.client.get("/api/memory").json()["items"]
        self.assertEqual([i["kind"] for i in items], ["real_bug"])
        self.assertIn("Received: 30", items[0]["text"])
        # QA Memory feeds the module's bug history in the Analysis Agent
        from backend.memory import real_bugs_in_module
        self.assertEqual(real_bugs_in_module("ada/shop", "cart"), 1)
        self.assertEqual(self.client.post(f"/api/memory/{items[0]['id']}/delete").status_code, 204)
        self.assertEqual(self.client.get("/api/memory").json()["items"], [])
        self.assertEqual(self.client.post(f"/api/memory/{items[0]['id']}/delete").status_code, 404)
        self.assertEqual(count(ApprovalLog, action_type="memory_delete"), 1)

    def test_secrets_never_reach_memory(self):
        self.pw = pw_report(("login works", "unexpected", "Expected token ghp_" + "z" * 36 + " password='hunter2pass'"))
        self.start(self.ready())
        text = row(MemoryEntry).text
        self.assertNotIn("ghp_zzz", text)
        self.assertNotIn("hunter2pass", text)
        self.assertNotIn("ghp_zzz", row(TestResult, outcome="real_bug").error_message)

    def test_a_broken_memory_never_stops_a_run(self):
        with mock.patch("backend.memory.embed", side_effect=RuntimeError("memory down")):
            run = self.start(self.ready())["run"]
        self.assertEqual(run["status"], "finished")
        self.assertEqual(count(MemoryEntry), 0)
