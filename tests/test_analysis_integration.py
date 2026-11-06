"""The Deliverable 2 integration, end to end through the real app.

Covers the path the consolidation is about:
    signed webhook -> background task -> Analysis Manager -> Analysis Agent -> risk_assessments
    -> GET /api/analysis/pull-requests -> the shape the Risk Analysis screen renders.

GitHub is faked at the network boundary only (`fetch_pr` and the two defect-history lookups).
Everything inside that boundary is the real code: the real rule engine, the real Manager with its
retry cap and escalation, the real database writes and the real API.

Two tests need a model and have none, which is the point of them: with no provider key the agent
cannot write the reasoning, the Manager escalates after its retry cap, and the rule-based label
must still reach the screen. The approved path is covered separately by replacing `run_manager`,
so the happy path is tested without depending on a live LLM.

Needs the built frontend (cd frontend; npm run build), like the rest of the suite.
"""
import hashlib
import hmac
import json
import os
import unittest
from unittest import mock

from sqlalchemy import select

from agents.risk_rules import assess
from backend.agent_db import AgentBase, RiskAssessment, init_agent_db
from backend.analysis_service import AgentUnavailable
from backend.db import Base, Project, SessionLocal, engine
from backend.settings import settings

from .test_crud import CrudTestCase, count, row

REPO = "ada/shop"
_SIGN = object()  # "sign this delivery correctly", so the empty string can mean an empty signature

# A pull request that touches payment code: the rules must call this High.
PR_INFO = {"title": "Refactor checkout session", "head": {"sha": "a" * 40}}
PR_FILES = [
    {"filename": "src/payments/session.ts", "additions": 120, "deletions": 40,
     "patch": "@@ -1 +1 @@\n-const a = 1;\n+const charge = stripe.createCharge(token);\n"},
    {"filename": "src/payments/tax.ts", "additions": 30, "deletions": 5, "patch": "@@ -1 +1 @@\n+const vat = 0.2;\n"},
    {"filename": "tests/payments.spec.ts", "additions": 20, "deletions": 0, "patch": None},
]
# What the rules must produce for the payload above, computed by the rules themselves so the test
# asserts "the screen shows what the engine decided", not a number copied by hand.
EXPECTED = assess(PR_FILES, 0)


def payload(action="opened", number=4, sha=PR_INFO["head"]["sha"], repo=REPO, title=PR_INFO["title"]):
    return {
        "action": action,
        "number": number,
        "pull_request": {
            "title": title,
            "html_url": f"https://github.com/{repo}/pull/{number}",
            "head": {"sha": sha, "ref": "feature"},
            "base": {"ref": "main"},
            "user": {"login": "hamza"},
        },
        "repository": {"full_name": repo},
    }


def approved_result(pr_id: str, facts: dict) -> dict:
    """What the Analysis Manager returns when it accepts the Analysis Agent's output."""
    return {
        "pr_id": pr_id, "status": "approved", "attempts": 1, "errors": [],
        "analysis": {
            "pr_id": pr_id,
            "risk_label": facts["risk_label"],
            "score": facts["score"],
            "risk_factors": facts["risk_factors"],
            "reasoning": "The change rewrites how a checkout session is charged and touches tax "
                         "calculation, so a mistake bills the wrong amount.",
            "suggested_test_areas": [
                "charging a session twice returns a single charge",
                "tax is applied before the discount, not after",
                "a declined card leaves no order behind",
            ],
            "model": "groq/openai/gpt-oss-20b",
        },
    }


class AnalysisTestCase(CrudTestCase):
    def setUp(self):
        # risk_assessments points at projects, so it is dropped before the app tables and
        # recreated after them.
        AgentBase.metadata.drop_all(engine)
        super().setUp()           # drops and recreates the five app tables
        init_agent_db()

        # The only fakes: the three calls that would reach github.com.
        self.fetch_pr = mock.patch("agents.analysis.fetch_pr", return_value=(PR_INFO, PR_FILES)).start()
        mock.patch("agents.analysis.count_fix_commits", return_value=0).start()
        mock.patch("agents.analysis.count_defects", return_value=0).start()

        # The agent caches the scored pull request per id, so clear it between tests.
        from agents.analysis import _CACHE, ANALYSES
        ANALYSES.clear()
        _CACHE.clear()

    # ---- helpers ----

    def deliver(self, body: dict, event="pull_request", signature=_SIGN, delivery="d-1"):
        """Posts a webhook delivery, signed the way GitHub signs it. TestClient runs the
        background task before returning, so the analysis has finished when this returns.

        `signature` defaults to a correct one. Pass a string to send that instead, including the
        empty string; pass None to send no signature header at all.
        """
        raw = json.dumps(body).encode()
        headers = {"x-github-event": event, "x-github-delivery": delivery,
                   "content-type": "application/json"}
        if signature is _SIGN:
            headers["x-hub-signature-256"] = (
                "sha256=" + hmac.new(settings.webhook_secret.encode(), raw, hashlib.sha256).hexdigest())
        elif signature is not None:
            headers["x-hub-signature-256"] = signature
        return self.client.post("/webhooks/github", content=raw, headers=headers)

    def feed(self, client=None):
        res = (client or self.client).get("/api/analysis/pull-requests")
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def fake_manager(self):
        """Replaces the ADK run with an approved result, and fills the agent's fact cache the way
        a real run would, so the service's read-back of the rule output is still exercised."""
        async def run_manager(pr_id, token=None):
            from agents.analysis import ANALYSES, score_pr
            facts = score_pr(pr_id, True, token)
            ANALYSES.setdefault(pr_id, {})["facts"] = facts
            return approved_result(pr_id, facts)
        return mock.patch("agents.runner.run_manager", side_effect=run_manager)


class WebhookToDatabaseTests(AnalysisTestCase):
    @mock.patch.dict(os.environ, {"GROQ_API_KEY": "", "OPENROUTER_API_KEY": "",
                                  "GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""})
    def test_rule_label_reaches_the_database_and_the_api_without_a_model(self):
        """No provider key, so the Manager escalates after its retry cap. The rule-based label,
        score and factor trace must still be stored and served.

        The provider keys are cleared explicitly rather than assumed absent: a real .env now has
        them, and this test must assert the no-key behaviour either way.
        """
        self.connected_user(repo=REPO)
        self.assertEqual(self.deliver(payload()).status_code, 202)

        stored = row(RiskAssessment, pr_number=4)
        self.assertIsNotNone(stored, "the webhook did not create a risk assessment")
        self.assertEqual(stored.risk_label, EXPECTED["risk_label"])
        self.assertEqual(stored.risk_label, "High")          # payment code, 215 lines
        self.assertEqual(stored.score, EXPECTED["score"])
        self.assertEqual(stored.base_label, EXPECTED["base_label"])
        self.assertEqual(stored.module, "payments")
        self.assertEqual(stored.files_changed, 3)
        self.assertEqual(stored.lines_changed, 215)
        self.assertEqual(stored.sensitivity, "high")
        self.assertEqual(stored.title, PR_INFO["title"])
        self.assertEqual(stored.author, "hamza")
        self.assertEqual(stored.head_sha, PR_INFO["head"]["sha"])
        self.assertEqual(stored.delivery_id, "d-1")

        # Escalated, not silently approved, and the reason is recorded rather than hidden.
        self.assertEqual(stored.state, "needs_human_review")
        self.assertEqual(stored.attempts, 3)                  # the Manager's retry cap
        self.assertTrue(stored.errors)
        self.assertIsNone(stored.reasoning)

        # And the screen gets the same values, with the factor trace parsed back out of JSON.
        item = self.feed()["items"][0]
        self.assertEqual(item["risk_label"], "High")
        self.assertEqual(item["state"], "needs_human_review")
        self.assertEqual(item["risk_factors"], EXPECTED["risk_factors"])
        self.assertEqual(item["test_areas"], [])
        self.assertEqual(item["pr_url"], f"https://github.com/{REPO}/pull/4")

    def test_an_approved_analysis_is_stored_and_served_in_full(self):
        self.connected_user(repo=REPO)
        with self.fake_manager():
            self.assertEqual(self.deliver(payload()).status_code, 202)

        stored = row(RiskAssessment, pr_number=4)
        self.assertEqual(stored.state, "scored")
        self.assertEqual(stored.attempts, 1)
        self.assertIsNone(stored.errors)
        self.assertEqual(stored.model_used, "groq/openai/gpt-oss-20b")

        item = self.feed()["items"][0]
        self.assertEqual(item["risk_label"], "High")
        self.assertEqual(item["score"], EXPECTED["score"])
        self.assertIn("checkout session", item["reasoning"])
        self.assertEqual(len(item["test_areas"]), 3)
        self.assertEqual(item["model_used"], "groq/openai/gpt-oss-20b")
        self.assertEqual(item["modules_touched"], ["payments", "tests"])

    def test_the_counts_the_screen_shows_come_from_the_stored_rows(self):
        self.connected_user(repo=REPO)
        with self.fake_manager():
            self.deliver(payload(number=4))
            # A second pull request that only touches documentation: the rules call this Low.
            self.fetch_pr.return_value = (
                {"title": "Fix a typo", "head": {"sha": "b" * 40}},
                [{"filename": "docs/readme.md", "additions": 2, "deletions": 1, "patch": None}],
            )
            self.deliver(payload(number=5, sha="b" * 40, title="Fix a typo"), delivery="d-2")

        feed = self.feed()
        self.assertEqual(feed["counts"]["total"], 2)
        self.assertEqual(feed["counts"]["High"], 1)
        self.assertEqual(feed["counts"]["Low"], 1)
        self.assertEqual(feed["counts"]["pending"], 0)
        self.assertEqual(feed["project"]["repo"], REPO)
        self.assertEqual([i["pr_number"] for i in feed["items"]], [5, 4])  # newest first

    def test_a_new_push_to_the_same_pull_request_is_a_new_assessment(self):
        """`synchronize` with a different head commit is new code, so it is scored again and the
        old assessment is kept rather than overwritten."""
        self.connected_user(repo=REPO)
        with self.fake_manager():
            self.deliver(payload(number=4))
            self.fetch_pr.return_value = (
                {"title": PR_INFO["title"], "head": {"sha": "c" * 40}},
                [{"filename": "docs/readme.md", "additions": 2, "deletions": 0, "patch": None}],
            )
            self.deliver(payload(action="synchronize", number=4, sha="c" * 40), delivery="d-2")

        self.assertEqual(count(RiskAssessment, pr_number=4), 2)
        # Counted once, at the risk of the newest push.
        self.assertEqual(self.feed()["counts"]["total"], 1)

    def test_a_repeated_delivery_is_not_analysed_twice(self):
        self.connected_user(repo=REPO)
        with self.fake_manager() as runner:
            self.deliver(payload())
            self.assertEqual(runner.call_count, 1)
            self.deliver(payload())                      # GitHub resends the same event
            self.assertEqual(runner.call_count, 1, "the agent ran again for an already scored PR")
        self.assertEqual(count(RiskAssessment, pr_number=4), 1)

    def test_a_crashing_agent_is_recorded_as_failed(self):
        self.connected_user(repo=REPO)
        with mock.patch("agents.runner.run_manager", side_effect=RuntimeError("provider is down")):
            self.assertEqual(self.deliver(payload()).status_code, 202)
        stored = row(RiskAssessment, pr_number=4)
        self.assertEqual(stored.state, "failed")
        self.assertIn("provider is down", stored.errors)
        self.assertEqual(self.feed()["counts"]["failed"], 1)

    def test_a_repository_connected_by_two_accounts_gets_one_assessment_each(self):
        self.connected_user(email="ada@example.com", repo=REPO)
        self.connected_user(email="bob@example.com", repo=REPO, client=self.new_client())
        with self.fake_manager():
            self.deliver(payload())
        self.assertEqual(count(RiskAssessment, pr_number=4), 2)
        with SessionLocal() as db:
            projects = db.scalars(select(Project).where(Project.repo == REPO)).all()
            self.assertEqual(len({p.id for p in projects}), 2)


class WebhookGuardTests(AnalysisTestCase):
    def test_a_bad_signature_never_reaches_the_agent(self):
        self.connected_user(repo=REPO)
        with self.fake_manager() as runner:
            for bad in ("sha256=deadbeef", "", "not-a-signature", None):
                self.assertEqual(self.deliver(payload(), signature=bad).status_code, 401)
            runner.assert_not_called()
        self.assertEqual(count(RiskAssessment), 0)

    def test_only_opened_synchronize_and_reopened_are_analysed(self):
        self.connected_user(repo=REPO)
        with self.fake_manager() as runner:
            for action in ("closed", "edited", "labeled", "assigned"):
                self.assertEqual(self.deliver(payload(action=action)).status_code, 202)
            runner.assert_not_called()
            self.assertEqual(count(RiskAssessment), 0)

            for n, action in enumerate(("opened", "synchronize", "reopened"), start=10):
                self.deliver(payload(action=action, number=n), delivery=f"d-{n}")
            self.assertEqual(runner.call_count, 3)

    def test_other_events_are_accepted_but_not_analysed(self):
        self.connected_user(repo=REPO)
        with self.fake_manager() as runner:
            for event in ("ping", "push", "issues"):
                res = self.deliver(payload(), event=event)
                self.assertEqual(res.status_code, 202)
                self.assertEqual(res.json(), {"received": event})
            runner.assert_not_called()

    def test_a_pull_request_on_an_unconnected_repository_is_ignored(self):
        self.connected_user(repo=REPO)
        with self.fake_manager() as runner:
            self.assertEqual(self.deliver(payload(repo="someone/else")).status_code, 202)
            runner.assert_not_called()
        self.assertEqual(count(RiskAssessment), 0)

    def test_a_payload_without_a_head_commit_is_ignored(self):
        self.connected_user(repo=REPO)
        broken = payload()
        broken["pull_request"]["head"] = {}
        with self.fake_manager() as runner:
            self.assertEqual(self.deliver(broken).status_code, 202)
            runner.assert_not_called()
        self.assertEqual(count(RiskAssessment), 0)


class AnalysisApiTests(AnalysisTestCase):
    def test_every_route_needs_an_account(self):
        for method, path, body in (("get", "/api/analysis/pull-requests", None),
                                   ("get", "/api/analysis/pull-requests/1", None),
                                   ("post", "/api/analysis/analyse", {"pr_number": 4})):
            res = getattr(self.client, method)(path, **({"json": body} if body else {}))
            self.assertEqual(res.status_code, 401, f"{method} {path}")
            self.assertEqual(res.json()["detail"], "Sign in first")

    def test_without_a_project_the_screen_gets_an_empty_feed_not_an_error(self):
        self.linked_user()
        feed = self.feed()
        self.assertIsNone(feed["project"])
        self.assertEqual(feed["items"], [])

    def test_one_assessment_can_be_read_on_its_own(self):
        self.connected_user(repo=REPO)
        with self.fake_manager():
            self.deliver(payload())
        stored = row(RiskAssessment, pr_number=4)
        res = self.client.get(f"/api/analysis/pull-requests/{stored.id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["risk_label"], "High")

    def test_another_accounts_assessment_is_not_readable(self):
        self.connected_user(email="ada@example.com", repo=REPO)
        with self.fake_manager():
            self.deliver(payload())
        mine = row(RiskAssessment, pr_number=4)

        other = self.new_client()
        self.connected_user(email="bob@example.com", repo="bob/other", client=other)
        res = other.get(f"/api/analysis/pull-requests/{mine.id}")
        self.assertEqual(res.status_code, 404)  # 404, not 403: ids of other accounts stay invisible

    def test_a_missing_assessment_is_404(self):
        self.connected_user(repo=REPO)
        self.assertEqual(self.client.get("/api/analysis/pull-requests/9999").status_code, 404)
        self.assertEqual(self.client.get("/api/analysis/pull-requests/0").status_code, 422)

    def test_analyse_now_scores_a_pull_request_on_demand(self):
        self.connected_user(repo=REPO)
        with self.fake_manager():
            res = self.client.post("/api/analysis/analyse", json={"pr_number": 4})
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["risk_label"], "High")
        self.assertEqual(body["state"], "scored")
        self.assertEqual(count(RiskAssessment, pr_number=4), 1)

    def test_analyse_now_without_a_project_is_refused(self):
        self.linked_user()
        res = self.client.post("/api/analysis/analyse", json={"pr_number": 4})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["detail"], "Connect a repository first")

    def test_analyse_now_rejects_a_pull_request_github_cannot_read(self):
        self.connected_user(repo=REPO)
        self.fetch_pr.side_effect = RuntimeError("404 Not Found")
        res = self.client.post("/api/analysis/analyse", json={"pr_number": 999})
        self.assertEqual(res.status_code, 502)
        self.assertIn("Could not fetch", res.json()["detail"])
        self.assertEqual(count(RiskAssessment), 0)

    def test_analyse_now_validates_the_pull_request_number(self):
        self.connected_user(repo=REPO)
        for bad in ({"pr_number": 0}, {"pr_number": -3}, {"pr_number": "abc"}, {}):
            self.assertEqual(self.client.post("/api/analysis/analyse", json=bad).status_code, 422, bad)

    def test_the_agent_being_unavailable_is_a_503_not_a_crash(self):
        self.connected_user(repo=REPO)
        with mock.patch("backend.analysis_service._load_runner",
                        side_effect=AgentUnavailable("Analysis Agent is unavailable: ImportError: no google.adk")):
            res = self.client.post("/api/analysis/analyse", json={"pr_number": 4})
        self.assertEqual(res.status_code, 503)
        self.assertIn("unavailable", res.json()["detail"])


class CleanupTests(AnalysisTestCase):
    def test_disconnecting_removes_the_assessments(self):
        self.connected_user(repo=REPO)
        with self.fake_manager():
            self.deliver(payload())
        self.assertEqual(count(RiskAssessment), 1)

        self.assertEqual(self.client.post("/api/disconnect").status_code, 204)
        self.assertEqual(count(RiskAssessment), 0, "risk assessments outlived the project")
        self.assertEqual(count(Project), 0)

    def test_deleting_the_account_removes_the_assessments(self):
        from .test_crud import PASSWORD
        self.connected_user(repo=REPO)
        with self.fake_manager():
            self.deliver(payload())
        self.assertEqual(count(RiskAssessment), 1)

        res = self.client.post("/api/account/delete", json={"password": PASSWORD, "code": ""})
        self.assertEqual(res.status_code, 204, res.text)
        self.assertEqual(count(RiskAssessment), 0)


class ScopeTests(unittest.TestCase):
    """The Test & Execution Agent is out of this scope and must not have been dragged in."""

    def test_the_agents_package_holds_only_the_analysis_scope(self):
        import pathlib

        import agents
        names = {p.stem for p in pathlib.Path(agents.__file__).parent.glob("*.py")}
        self.assertEqual(names, {"__init__", "analysis", "events", "github_client", "llm",
                                 "manager", "models", "redact", "risk_rules", "runner", "trace"})
        for absent in ("steps", "runners", "selector", "classifier", "drafter", "store", "test_phase"):
            self.assertNotIn(absent, names, f"{absent} belongs to the Test Agent, not this scope")

    def test_the_app_tables_were_not_given_agent_columns(self):
        for model in Base.registry.mappers:
            table = model.class_.__tablename__
            if table in ("users", "projects", "spec_files", "collections", "recovery_codes"):
                for column in model.class_.__table__.columns.keys():
                    self.assertNotIn("risk", column, f"{table}.{column} looks like agent data")


if __name__ == "__main__":
    unittest.main()
