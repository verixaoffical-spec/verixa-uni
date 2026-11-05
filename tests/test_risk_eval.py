"""T-037: the analysis eval set. Labelled pull requests, scored by the real rules, with a recorded accuracy.

The expected labels are what a QA reviewer would call each change, written down BEFORE running the rules, and the
rules were not changed to fit them. They are a draft: the team should review them, because a label here is a judgement.
The changes are realistic examples written for this set, not recordings of real pull requests.

KNOWN_MISSES are real gaps in the rules, kept visible. Fix one by adding its word to the rules or to
HIGH_RISK_KEYWORDS / MEDIUM_RISK_KEYWORDS, then remove it from the list.

See the score with:  python -m tests.test_risk_eval
"""
import unittest

from agents.risk_rules import assess


def change(path, added=10, deleted=0, patch=None):
    return {"filename": path, "additions": added, "deletions": deleted, "patch": patch}


def many(count, folder, lines_each, extension="tsx"):
    return [change(f"src/{folder}/file{i}.{extension}", lines_each) for i in range(count)]


# (what the pull request is, its files, past fixes in the module, the label a reviewer would give)
CASES = [
    ("typo in the README", [change("README.md", 1, 1)], 0, "Low"),
    ("large documentation rewrite", [change(f"docs/page{i}.md", 100) for i in range(3)], 0, "Low"),
    ("a guide that mentions auth", [change("docs/auth-guide.md", 50)], 0, "Low"),
    ("new tests for login", [change("tests/test_login.py", 40)], 0, "Low"),
    ("spec that mentions password", [change("e2e/login.spec.ts", 30, patch="+password token secret")], 0, "Low"),
    ("small style change", [change("src/ui/button.css", 10)], 0, "Low"),
    ("rename a helper", [change("src/utils/dates.py", 15, 15), change("src/utils/format.py", 5)], 0, "Low"),
    ("folder name only looks like auth", [change("src/authors/list.py", 5)], 0, "Low"),
    ("folder name only looks like token", [change("src/tokenizer/parse.py", 5)], 0, "Low"),
    ("one passing mention of a token", [change("src/utils/log.py", 3, patch="+# the token count")], 0, "Low"),
    ("lock file regenerated", [change("package-lock.json", 3000, 2000)], 0, "Low"),
    ("nothing changed", [], 0, "Low"),

    ("a profile page", [change("src/user/profile.py", 30)], 0, "Medium"),
    ("a config value", [change("src/config/settings.py", 10)], 0, "Medium"),
    ("a database migration", [change("db/migrations/0042_add_index.sql", 12)], 0, "Medium"),
    ("order status", [change("src/orders/status.py", 100), change("src/orders/view.py", 20)], 0, "Medium"),
    ("medium sized feature", many(5, "dashboard", 30), 0, "Medium"),
    ("new module with no history", many(8, "reports", 55), 0, "Medium"),
    ("small change in a module that breaks often", [change("src/search/rank.py", 5)], 12, "Medium"),
    ("two files in a module with some bugs", [change("src/search/a.py", 25), change("src/search/b.py", 25)], 5, "Medium"),
    ("container image change", [change("Dockerfile", 5)], 0, "Medium"),

    ("one line in login", [change("src/auth/login.py", 1)], 0, "High"),
    ("payment tax", [change("src/payments/tax.py", 10)], 0, "High"),
    ("checkout flow", [change("src/checkout/cart.py", 60), change("src/checkout/pay.py", 30)], 0, "High"),
    ("roles and permissions", [change("src/rbac/roles.py", 20)], 0, "High"),
    ("helper that handles passwords and tokens", [change("src/utils/helpers.py", 8, patch="+password = token")], 0, "High"),
    ("huge change", many(12, "ui", 50), 0, "High"),
    ("medium change in a module that breaks often", many(5, "search", 40, "py"), 12, "High"),
    ("password hashing helper", [change("src/lib/hash.py", 20, patch="+digest = bcrypt.hash(value)")], 0, "High"),
    ("cross-site settings", [change("src/middleware/cors.py", 15)], 0, "High"),
]

# What the rules get wrong today: (what the pull request is, what the rules answer)
KNOWN_MISSES = {
    "lock file regenerated": "Medium",         # one huge generated file counts as a big change
    "container image change": "Low",           # build files are not a sensitive area yet
    "password hashing helper": "Low",          # bcrypt and hash are not sensitive words yet
    "cross-site settings": "Low",              # cors is not a sensitive word yet
}
TARGET = 0.8


def score() -> tuple[float, dict]:
    misses = {}
    for name, files, defects, expected in CASES:
        got = assess(files, defects)["risk_label"]
        if got != expected:
            misses[name] = got
    return 1 - len(misses) / len(CASES), misses


class RiskEvalTests(unittest.TestCase):
    def test_the_set_is_the_size_the_backlog_asks_for_with_every_label(self):
        self.assertTrue(20 <= len(CASES) <= 30, len(CASES))
        self.assertEqual({label for *_, label in CASES}, {"Low", "Medium", "High"})
        self.assertEqual(len({name for name, *_ in CASES}), len(CASES))

    def test_accuracy_meets_the_target(self):
        self.assertGreaterEqual(score()[0], TARGET)

    def test_the_only_misses_are_the_known_ones(self):
        self.assertEqual(score()[1], KNOWN_MISSES)


if __name__ == "__main__":
    accuracy, missed = score()
    print(f"{len(CASES) - len(missed)} of {len(CASES)} correct: {accuracy:.0%} (target {TARGET:.0%})")
    for name, got in missed.items():
        print(f"  missed: {name}: rules said {got}")
