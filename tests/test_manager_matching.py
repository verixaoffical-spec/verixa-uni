"""The Manager's "is this answer about the change?" check, with real answers from scripts/agent_eval_check.py.

Case E5 removed one login check. The model answered correctly twice, and the Manager rejected it three times,
because "unauthenticated" did not count as the diff's isAuthenticated and 401 did not count at all.
"""
import unittest

from agents.manager import about_this_change, areas_about_this_change

DIFF = "app.js (+0/-1)\n@@ -12 +11,0 @@\n-  if (!isAuthenticated(req)) return res.status(401).send('Login required');\n"


class RealAnswers(unittest.TestCase):
    def test_correct_answers_about_a_removed_login_check_are_accepted(self):
        areas = ["Unauthenticated request to the affected endpoint returns 200 instead of 401",
                 "Authenticated request to the same endpoint still returns expected success response",
                 "Unauthenticated request with an expired session is still refused elsewhere"]
        self.assertTrue(areas_about_this_change(areas, DIFF))
        self.assertTrue(about_this_change("The change removes the authentication check in app.js.", DIFF))

    def test_answers_about_something_else_are_still_rejected(self):
        unrelated = ["pods autoscale under load", "the ingress reloads its config", "metrics are exported"]
        self.assertFalse(areas_about_this_change(unrelated, DIFF))
        self.assertFalse(about_this_change("This adds redirect loop detection to the Kubernetes ingress.", DIFF))

    def test_short_words_never_match_by_containing_each_other(self):
        # "req" is in "request", but words under 5 letters only ever match exactly
        self.assertFalse(areas_about_this_change(["the frequency of requests is logged", "a queue drains"], "x.js (+1/-0)\n+const req = 1;\n"))


if __name__ == "__main__":
    unittest.main()
