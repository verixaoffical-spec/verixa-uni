"""The rule engine behind the risk label (agents/risk_rules.py), reused unchanged from the
multi-agents repository. These are the acceptance criteria for T-031 (rule-based risk score) and
T-033 (new-module size-based scoring).

Pure functions, so no database, no network and no model. The label is decided here, in code, and
never by an LLM, which is what makes it testable at all.
"""
import unittest

from agents.risk_rules import (
    assess,
    defect_points,
    is_test_or_doc,
    module_of,
    sensitivity,
    size_points,
    tokens,
)


def f(filename: str, additions: int = 5, deletions: int = 0, patch: str | None = None) -> dict:
    """A changed file in the shape the GitHub API returns."""
    return {"filename": filename, "additions": additions, "deletions": deletions, "patch": patch}


class TokenTests(unittest.TestCase):
    def test_paths_split_on_case_and_punctuation(self):
        self.assertIn("payment", tokens("src/payments/tax.py"))
        self.assertIn("token", tokens("lib/authToken.ts"))  # camelCase is split

    def test_plurals_are_normalised_but_double_s_is_kept(self):
        self.assertIn("test", tokens("tests/x.ts"))
        self.assertIn("class", tokens("class.ts"))  # not "clas"

    def test_test_and_doc_files_are_recognised(self):
        for path in ("tests/a.ts", "src/a.spec.ts", "docs/guide.md", "NOTES.txt", "x/__tests__/b.ts"):
            self.assertTrue(is_test_or_doc(path), path)
        for path in ("src/payments/tax.py", "app/documents/store.ts"):
            self.assertFalse(is_test_or_doc(path), path)


class ModuleTests(unittest.TestCase):
    def test_wrapper_directories_are_skipped(self):
        self.assertEqual(module_of("src/payments/tax.py"), ("payments", "src/payments"))
        self.assertEqual(module_of("packages/auth/login.ts"), ("auth", "packages/auth"))

    def test_plain_folder_is_the_module(self):
        self.assertEqual(module_of("payments/tax.py"), ("payments", "payments"))

    def test_a_file_at_the_root_has_no_module(self):
        self.assertEqual(module_of("README.md"), ("root", ""))

    def test_a_wrapper_directory_with_nothing_under_it_is_the_module(self):
        self.assertEqual(module_of("src/app.ts"), ("src", "src"))


class PointTests(unittest.TestCase):
    def test_size_points_rise_with_files_and_lines(self):
        self.assertEqual(size_points(1, 10), 2)      # smallest possible
        self.assertEqual(size_points(4, 100), 4)     # both at the middle threshold
        self.assertEqual(size_points(10, 500), 6)    # both at the top threshold
        self.assertEqual(size_points(99, 9999), 6)   # and it stops there

    def test_defect_points_are_capped_at_three(self):
        self.assertEqual(defect_points(0), 0)
        self.assertEqual(defect_points(-1), 0)       # negative is treated as none
        self.assertEqual(defect_points(3), 1)
        self.assertEqual(defect_points(4), 2)
        self.assertEqual(defect_points(10), 3)
        self.assertEqual(defect_points(40), 3)       # a module with 40 is not worse than one with 10


class SensitivityTests(unittest.TestCase):
    def test_a_security_word_in_the_path_is_high(self):
        got = sensitivity([f("src/payments/tax.py")])
        self.assertEqual(got["level"], "high")
        self.assertTrue(got["reasons"])

    def test_a_user_word_in_the_path_is_medium(self):
        self.assertEqual(sensitivity([f("profile/edit.ts")])["level"], "medium")

    def test_two_security_words_in_the_changed_code_are_high(self):
        patch = "@@ -1 +1 @@\n-const a = 1;\n+const token = jwt.sign(payload);\n"
        self.assertEqual(sensitivity([f("core/util.ts", patch=patch)])["level"], "high")

    def test_one_security_word_in_the_changed_code_is_not_enough(self):
        patch = "@@ -1 +1 @@\n+const token = 1;\n"
        self.assertEqual(sensitivity([f("core/util.ts", patch=patch)])["level"], "none")

    def test_context_lines_of_a_diff_are_ignored(self):
        # Only + and - lines are the change. +++ and --- are file headers, not code.
        patch = "--- a/core/util.ts\n+++ b/core/util.ts\n const token = jwt.x;\n+const a = 1;\n"
        self.assertEqual(sensitivity([f("core/util.ts", patch=patch)])["level"], "none")

    def test_test_files_never_raise_sensitivity(self):
        patch = "@@ -1 +1 @@\n+const token = jwt.sign(password);\n"
        self.assertEqual(sensitivity([f("tests/auth.spec.ts", patch=patch)])["level"], "none")

    def test_nothing_changed_is_not_sensitive(self):
        self.assertEqual(sensitivity([]), {"level": "none", "reasons": []})


class AssessTests(unittest.TestCase):
    def test_a_tiny_documentation_change_is_low(self):
        got = assess([f("docs/readme.md", 5, 0)], 0)
        self.assertEqual((got["risk_label"], got["base_label"], got["score"]), ("Low", "Low", 2))
        self.assertEqual(got["sensitivity"], "none")

    def test_security_code_is_raised_to_high_even_when_the_score_is_medium(self):
        got = assess([f("src/payments/tax.py", 10, 0)], 0)
        self.assertEqual(got["base_label"], "Medium")   # score 4 on its own
        self.assertEqual(got["risk_label"], "High")     # the minimum label wins
        self.assertEqual(got["sensitivity"], "high")
        self.assertTrue(any("raised to High" in line for line in got["risk_factors"]))

    def test_user_code_is_raised_to_at_least_medium(self):
        got = assess([f("profile/edit.ts", 1, 0)], 0)
        self.assertEqual(got["base_label"], "Low")      # score 3
        self.assertEqual(got["risk_label"], "Medium")

    def test_a_new_module_with_no_history_is_scored_by_size(self):
        """T-033. No defect history anywhere, so the label comes from how big the change is."""
        small = assess([f("widgets/a.go", 10, 0)], 0)
        self.assertEqual(small["risk_label"], "Low")
        self.assertEqual(small["defect_points"], 0)

        large = assess([f(f"widgets/w{i}.go", 30, 20) for i in range(12)], 0)
        self.assertEqual(large["defect_points"], 0)     # still no history
        self.assertEqual(large["size_points"], 6)
        self.assertEqual(large["base_label"], "Medium")
        self.assertEqual(large["risk_label"], "High")   # raised by "very large change"
        self.assertTrue(any("very large change" in line for line in large["risk_factors"]))

    def test_defect_history_pushes_the_score_up(self):
        # 4 files and 120 lines: 2 points for the file count, 2 for the lines. No sensitive paths.
        files = [f(f"widgets/w{i}.go", 30, 0) for i in range(4)]
        self.assertEqual(assess(files, 0)["size_points"], 4)
        self.assertEqual(assess(files, 0)["risk_label"], "Medium")  # score 4
        self.assertEqual(assess(files, 10)["risk_label"], "High")   # score 7 with 3 defect points

    def test_the_factor_trace_always_explains_all_three_inputs(self):
        got = assess([f("widgets/a.go", 10, 0)], 0)
        joined = " ".join(got["risk_factors"])
        for expected in ("size:", "defect history:", "sensitive area:", "score"):
            self.assertIn(expected, joined)

    def test_a_failed_defect_lookup_is_recorded_rather_than_hidden(self):
        got = assess([f("widgets/a.go", 10, 0)], 0, "commits lookup failed: 403")
        self.assertTrue(any("commits lookup failed" in line for line in got["risk_factors"]))

    def test_an_empty_pull_request_still_produces_a_valid_label(self):
        got = assess([], 0)
        self.assertEqual(got["risk_label"], "Low")
        self.assertEqual(got["lines_changed"], 0)


if __name__ == "__main__":
    unittest.main()
