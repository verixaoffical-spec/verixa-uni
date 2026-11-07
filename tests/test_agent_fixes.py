"""The three fixes from the agent evaluation (AGENT_EVAL_REPORT.md):

1. Rules for dangerous removals and secrets written into code, so they are never scored Low.
2. No code shown, no code tests: the prompt says so, and the Manager rejects tests about functions or routes.
3. The model may disagree in a "concern", which is stored and shown, while the rule label stays final.
"""
import json
import unittest
from unittest import mock

from agents import analysis
from agents.analysis import ANALYSES, _instruction
from agents.manager import validate
from agents.risk_rules import assess, risky_removals
from backend.agent_db import RiskAssessment, to_json

from .test_agents_real import AgentCase, reply
from .test_analysis_integration import AnalysisTestCase, payload
from .test_crud import row
from .test_risk_rules import f

KEY = "AKIA" + "Q7XZ3EXAMPLEK2LM"


def removed(path, line, added=""):
    patch = f"@@ -1,2 +1,1 @@\n-{line}\n" + (f"+{added}\n" if added else "")
    return f(path, 1 if added else 0, 1, patch)


class DangerousRemovals(unittest.TestCase):
    def label(self, *files):
        return assess(list(files), 0)["risk_label"]

    def test_a_removed_login_check_is_high_however_small(self):
        guard = "  if (!isAuthenticated(req)) return res.status(401).send('Login required');"
        a = assess([removed("app.js", guard)], 0)
        self.assertEqual((a["base_label"], a["risk_label"]), ("Low", "High"))
        self.assertTrue(any(x.startswith("removal: removed a login or permission check in app.js") for x in a["risk_factors"]))

    def test_other_guards_in_other_languages(self):
        for path, line in (("views.py", "@login_required"), ("api/orders.py", "    if not user.is_admin: abort(403)"),
                           ("routes/admin.ts", "router.use(requireAuth);"), ("svc.go", "if !hasPermission(user, \"edit\") {"),
                           ("app.js", "app.use(csrf());"), ("server.js", "app.use(rateLimit({ max: 100 }));")):
            self.assertEqual(self.label(removed(path, line)), "High", line)

    def test_removed_input_checks_and_error_handling_are_medium(self):
        self.assertEqual(self.label(removed("lib/forms.js", "  validateEmail(body.email);")), "Medium")
        self.assertEqual(self.label(removed("lib/io.py", "    except OSError:")), "Medium")
        self.assertEqual(self.label(removed("lib/io.js", "  } catch (err) {")), "Medium")

    def test_removed_test_cases_are_medium(self):
        self.assertEqual(self.label(removed("tests/cart.spec.ts", "test('a declined card makes no order', async () => {")), "Medium")

    def test_a_check_that_is_moved_or_added_does_not_count(self):
        guard = "if (!isAuthenticated(req)) return res.status(401);"
        self.assertEqual(risky_removals([removed("app.js", "  " + guard, "    " + guard)]), [])
        self.assertEqual(risky_removals([f("app.js", 1, 0, f"@@ -0,0 +1 @@\n+{guard}\n")]), [])

    def test_docs_and_ordinary_lines_do_not_trigger(self):
        self.assertEqual(risky_removals([removed("README.md", "Call isAuthenticated before every route")]), [])
        self.assertEqual(risky_removals([removed("lib/format.js", "const total = items.length;")]), [])


class SecretsInCode(unittest.TestCase):
    def setUp(self):
        analysis._CACHE.clear()
        self.addCleanup(analysis._CACHE.clear)

    def score(self, patch):
        pr = {"title": "Storage client", "head": {"sha": "a" * 40}, "base": {"sha": "b" * 40, "repo": {"id": 1}}}
        with mock.patch.object(analysis, "fetch_pr", return_value=(pr, [f("src/storage/client.ts", 2, 1, patch)])), \
                mock.patch.object(analysis, "count_fix_commits", return_value=0), mock.patch.object(analysis, "count_defects", return_value=0):
            return analysis.score_pr("ada/shop#3")

    def test_an_added_secret_is_high(self):
        facts = self.score(f"@@ -0,0 +1,2 @@\n+const accessKey = '{KEY}';\n+export const client = new S3Client({{ accessKey }});\n")
        self.assertEqual(facts["risk_label"], "High")
        self.assertIn("secret in code: 1 value(s) that look like a key or password were added", facts["risk_factors"])
        self.assertNotIn(KEY, json.dumps(facts))

    def test_removing_a_secret_is_a_fix_not_a_risk(self):
        facts = self.score(f"@@ -1,2 +1,1 @@\n-const accessKey = '{KEY}';\n+const accessKey = process.env.KEY;\n")
        self.assertNotEqual(facts["risk_label"], "High")


class NoCodeShown(AgentCase):
    def setUp(self):
        super().setUp()
        self.fetch.return_value = ({**self.fetch.return_value[0], "title": "Move date helpers"}, [f("src/utils/dates.ts", 0, 0, None)])

    def test_the_prompt_tells_the_model_there_is_no_code(self):
        ANALYSES["ada/shop#4"] = {"facts": analysis.score_pr("ada/shop#4")}
        self.assertFalse(ANALYSES["ada/shop#4"]["facts"]["has_code"])
        ctx = mock.Mock()
        ctx.user_content.parts = [mock.Mock(text="Analyze ada/shop#4")]
        self.assertIn("No code or text change is shown", _instruction(ctx))

    def test_tests_about_invented_functions_are_rejected_then_fixed(self):
        invented = reply("Only src/utils/dates.ts was moved, with no content change, so the label is Low.",
                         ["date helper functions return a formatted string", "parsing throws on a bad date"])
        honest = reply("Only src/utils/dates.ts was moved, with no content change, so the label is Low.",
                       ["files importing src/utils/dates.ts still build after the move", "no file still uses the old path of dates.ts"])
        self.script(invented, honest)
        result = self.run_agent()
        self.assertEqual((result["status"], result["attempts"]), ("approved", 2))
        self.assertIn("no code changed", self.first.prompts[1])


class Concern(AgentCase):
    def test_a_concern_is_kept_and_the_label_is_not_changed(self):
        self.script(reply(concern="The createCharge call in src/payments/session.ts has no retry limit, so the risk may be higher than shown."))
        result = self.run_agent()
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["analysis"]["risk_label"], "High")
        self.assertIn("createCharge", result["analysis"]["concern"])

    def test_empty_or_none_concerns_are_stored_as_empty(self):
        for value in ("", "none", None):
            self.script(reply(concern=value))
            self.assertEqual(self.run_agent()["analysis"]["concern"], "")

    def test_a_concern_about_something_else_is_rejected(self):
        self.script(reply(concern="Kubernetes ingress pods may not autoscale under heavy load."), reply())
        result = self.run_agent()
        self.assertEqual(result["attempts"], 2)
        self.assertIn("concern must name the changed file", self.first.prompts[1])

    def test_a_concern_cannot_wave_the_change_through(self):
        self.script(reply(concern="session.ts is completely safe, createCharge needs no testing."), reply())
        self.assertEqual(self.run_agent()["attempts"], 2)


class ConcernIsSavedAndServed(AnalysisTestCase):
    def test_the_concern_reaches_the_database_and_the_api(self):
        self.connected_user()

        async def run_manager(pr_id, token=None):
            from agents.analysis import score_pr
            facts = score_pr(pr_id, True, token)
            ANALYSES.setdefault(pr_id, {})["facts"] = facts
            return {"pr_id": pr_id, "status": "approved", "attempts": 1, "errors": [],
                    "analysis": {"risk_label": facts["risk_label"], "reasoning": "x" * 30, "suggested_test_areas": ["a", "b"],
                                 "model": "fake", "concern": "session.ts charges without a retry limit"}}
        with mock.patch("agents.runner.run_manager", side_effect=run_manager):
            self.assertEqual(self.deliver(payload()).status_code, 202)
        saved = row(RiskAssessment, pr_number=4)
        self.assertEqual(saved.concern, "session.ts charges without a retry limit")
        self.assertEqual(self.feed()["items"][0]["concern"], "session.ts charges without a retry limit")
        self.assertEqual(to_json(saved)["risk_label"], saved.risk_label)


if __name__ == "__main__":
    unittest.main()
