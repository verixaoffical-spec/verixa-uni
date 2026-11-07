"""The CI check: a failing build or test run on a pull request's commit raises its risk to High.

Whatever a change looks like (a removed function, a typo, a broken import), if the repository's own CI fails on
the commit, the change breaks something. GitHub is faked at the network boundary only.
"""
import os
import unittest
from unittest import mock

from agents import analysis, github_client
from agents.risk_rules import assess
from backend.agent_db import RiskAssessment
from backend.live import describe

from .test_analysis_integration import AnalysisTestCase, PR_INFO, payload
from .test_crud import row
from .test_risk_rules import f

SHA = PR_INFO["head"]["sha"]


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"GitHub answered {self.status_code}")


def fake_github(runs=(), statuses=(), status=200):
    """Replaces httpx.Client in github_client with one that answers the two CI reads."""
    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            if url.endswith("/check-runs"):
                return FakeResponse({"check_runs": list(runs)}, status)
            return FakeResponse({"statuses": list(statuses)}, status)
    return mock.patch.object(github_client.httpx, "Client", Client)


def run(name, status="completed", conclusion="success"):
    return {"name": name, "status": status, "conclusion": conclusion}


class ReadingCI(unittest.TestCase):
    def ci(self, **kw):
        with fake_github(**kw):
            return github_client.ci_status("ada/shop", SHA)

    def test_a_failed_check_run_is_a_failure(self):
        ci = self.ci(runs=[run("build"), run("tests", conclusion="failure")])
        self.assertEqual((ci["state"], ci["failed"], ci["passed"]), ("failure", ["tests"], 1))

    def test_older_ci_reporting_commit_statuses_is_read_too(self):
        ci = self.ci(statuses=[{"context": "ci/jenkins", "state": "error"}])
        self.assertEqual((ci["state"], ci["failed"]), ("failure", ["ci/jenkins"]))

    def test_running_checks_are_pending(self):
        self.assertEqual(self.ci(runs=[run("build"), run("tests", status="in_progress", conclusion=None)])["state"], "pending")

    def test_all_passing_is_success_and_nothing_is_none(self):
        self.assertEqual(self.ci(runs=[run("build"), run("lint", conclusion="skipped")])["state"], "success")
        self.assertEqual(self.ci()["state"], "none")

    def test_a_cancelled_run_is_not_a_failure(self):
        # A newer push cancels the older run. That says nothing about the code.
        self.assertEqual(self.ci(runs=[run("build", conclusion="cancelled"), run("tests")])["state"], "success")

    def test_api_errors_are_raised_for_the_caller(self):
        with fake_github(status=403), self.assertRaises(RuntimeError):
            github_client.ci_status("ada/shop", SHA)


class RulesWithCI(unittest.TestCase):
    small = [f("README.md", 1, 1), f("app.js", 2, 1, "@@\n-function calculateTotal(items) {\n")]

    def test_failing_ci_raises_a_small_change_to_high(self):
        a = assess(self.small, 0, ci={"state": "failure", "failed": ["tests"], "pending": [], "passed": 1})
        self.assertEqual((a["base_label"], a["risk_label"]), ("Low", "High"))
        self.assertIn("ci: failing on this commit - tests", a["risk_factors"])
        self.assertIn("raised to High: the build or tests fail on this commit", a["risk_factors"][-1])

    def test_passing_pending_or_missing_ci_never_changes_the_label(self):
        for state in ("success", "pending", "none", "unknown"):
            a = assess(self.small, 0, ci={"state": state, "failed": [], "pending": [], "passed": 2})
            self.assertEqual(a["risk_label"], "Low", state)
            self.assertTrue(any(line.startswith("ci:") for line in a["risk_factors"]), state)

    def test_no_ci_check_adds_no_line(self):
        self.assertFalse(any(line.startswith("ci:") for line in assess(self.small, 0)["risk_factors"]))


@mock.patch.dict(os.environ, {"AGENT_CI_CHECK": "1"})
class AgentReadsCI(unittest.TestCase):
    def setUp(self):
        analysis._CACHE.clear()
        self.addCleanup(analysis._CACHE.clear)
        pr = {"title": "Rename a helper", "head": {"sha": SHA}, "base": {"sha": "b" * 40, "repo": {"id": 1}}}
        for name, value in (("fetch_pr", (pr, [f("app.js", 1, 3)])), ("count_fix_commits", 0), ("count_defects", 0)):
            patcher = mock.patch.object(analysis, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_one_line_change_that_breaks_ci_is_high(self):
        with mock.patch.object(analysis, "ci_status", return_value={"state": "failure", "failed": ["unit tests"], "pending": [], "passed": 0}) as ci:
            facts = analysis.score_pr("ada/shop#9", token="t")
        ci.assert_called_once_with("ada/shop", SHA, "t")
        self.assertEqual(facts["risk_label"], "High")
        self.assertIn("ci: failing on this commit - unit tests", facts["risk_factors"])

    def test_when_github_will_not_say_the_score_still_happens_and_says_so(self):
        with mock.patch.object(analysis, "ci_status", side_effect=RuntimeError("403")):
            facts = analysis.score_pr("ada/shop#9", token="t")
        self.assertEqual(facts["status"], "ok")
        self.assertEqual(facts["risk_label"], "Low")
        self.assertTrue(any("ci: could not be read" in line for line in facts["risk_factors"]))

    def test_the_switch_turns_it_off(self):
        with mock.patch.dict(os.environ, {"AGENT_CI_CHECK": "0"}), mock.patch.object(analysis, "ci_status") as ci:
            analysis.score_pr("ada/shop#9", token="t")
        ci.assert_not_called()


class CIFinishingLater(AnalysisTestCase):
    """The pull request was scored while CI was still running. GitHub's check_suite event says it finished."""

    def setUp(self):
        super().setUp()
        # A small change that the rules call Low: removing a helper's first line, nothing sensitive
        self.fetch_pr.return_value = (PR_INFO, [f("lib/format.js", 0, 1, "@@ -1 +0,0 @@\n-function formatPrice(n) {\n")])
        self.connected_user()
        with self.fake_manager():
            self.assertEqual(self.deliver(payload()).status_code, 202)
        saved = row(RiskAssessment, pr_number=4)
        self.assertEqual((saved.state, saved.risk_label), ("scored", "Low"))

    def suite(self, action="completed", sha=SHA):
        return {"action": action, "check_suite": {"head_sha": sha, "conclusion": "failure"},
                "repository": {"full_name": "ada/shop"}}

    def finish(self, ci, **kw):
        with mock.patch.object(github_client, "ci_status", return_value=ci) as read:
            res = self.deliver(self.suite(**kw), event="check_suite", delivery="cs-1")
        self.assertEqual(res.status_code, 202)
        return read

    def test_a_failure_raises_the_saved_label_to_high(self):
        before = row(RiskAssessment, pr_number=4)
        self.finish({"state": "failure", "failed": ["build"], "pending": [], "passed": 0})
        after = row(RiskAssessment, pr_number=4)
        self.assertEqual(after.risk_label, "High")
        self.assertIn("ci: failing on this commit - build", after.risk_factors)
        self.assertEqual(after.base_label, before.base_label)  # the rule result is kept, only raised
        feed = self.feed()["items"][0]
        self.assertEqual(feed["risk_label"], "High")

    def test_passing_ci_never_lowers_or_changes_the_label(self):
        label = row(RiskAssessment, pr_number=4).risk_label
        self.finish({"state": "success", "failed": [], "pending": [], "passed": 3})
        after = row(RiskAssessment, pr_number=4)
        self.assertEqual(after.risk_label, label)
        self.assertIn("ci: all 3 check(s) passed", after.risk_factors)

    def test_a_second_event_replaces_the_ci_line_instead_of_adding_one(self):
        self.finish({"state": "failure", "failed": ["build"], "pending": [], "passed": 0})
        self.finish({"state": "failure", "failed": ["build"], "pending": [], "passed": 0})
        factors = row(RiskAssessment, pr_number=4).risk_factors
        self.assertEqual(factors.count("ci: failing"), 1)

    def test_other_commits_and_unfinished_suites_are_ignored(self):
        self.assertFalse(self.finish({"state": "failure"}, sha="c" * 40).called)
        self.assertFalse(self.finish({"state": "failure"}, action="requested").called)

    def test_a_check_suite_with_a_bad_signature_is_refused(self):
        res = self.deliver(self.suite(), event="check_suite", signature="sha256=wrong")
        self.assertEqual(res.status_code, 401)


class LiveMessages(unittest.TestCase):
    def line(self, event, **fields):
        return {"at": "2026-11-07T10:00:00+00:00", "run_id": None, "pr_id": "ada/shop#4", "event": event, **fields}

    def test_ci_steps_are_shown(self):
        self.assertIn("failing on this commit (tests)", describe(self.line("github.ci_read", state="failure", failed=["tests"]))["text"])
        self.assertIn("still running", describe(self.line("github.ci_read", state="pending"))["text"])
        raised = describe(self.line("ci.updated", state="failure", raised=True))
        self.assertEqual((raised["text"], raised["done"]), ("CI finished and is failing, so the risk was raised to High", True))


if __name__ == "__main__":
    unittest.main()
