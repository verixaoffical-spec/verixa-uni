"""AT-38: a secret in a pull request never reaches the model provider, while the model can still explain the change."""
import unittest

from agents import analysis
from agents.analysis import ANALYSES
from agents.redact import HIDDEN, hide_secrets

from .test_agents_real import AgentCase, FILES, PR, PR_ID, reply

AWS = "AKIAIOSFODNN7" + "EXAMPLE"  # split, so secret scanners do not trip over this test
GITHUB = "ghp_" + "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6"
STRIPE = "sk_live_" + "51Habcdefghijklmnop"
SLACK = "xoxb-" + "123456789012-abcdefghijkl"
JWT = "eyJhbGciOiJIUzI1NiJ9." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"


class HidingSecrets(unittest.TestCase):
    def test_known_key_formats_are_hidden(self):
        for secret in (AWS, GITHUB, STRIPE, SLACK, JWT, "gsk_" + "abcdefghijklmnop1234", "AIza" + "SyA1234567890abcdefghijklmnopqrstuv"):
            with self.subTest(secret=secret[:6]):
                text, found = hide_secrets(f"+const key = {secret};\n")
                self.assertNotIn(secret, text)
                self.assertEqual(found, 1)

    def test_values_given_to_secret_names_are_hidden_and_the_names_stay(self):
        for line, name in (('password = "hunter2hunter"', "password"), ("DB_PASSWORD: 'correct-horse'", "DB_PASSWORD"),
                           ('{"api_key": "abc123def456"}', "api_key"), ("API_KEY=abc123def456ghi789", "API_KEY"),
                           ("client_secret => `s3cr3tvalue`", "client_secret"), ("config.auth_token = 'tok_12345678'", "auth_token")):
            with self.subTest(line=line):
                text, found = hide_secrets(line)
                self.assertEqual(found, 1, text)
                self.assertIn(HIDDEN, text)
                self.assertIn(name, text)

    def test_a_password_inside_a_database_address_is_hidden(self):
        text, found = hide_secrets("DATABASE_URL=postgres://admin:s3cretPw@db.example.com/shop")
        self.assertNotIn("s3cretPw", text)
        self.assertIn("db.example.com", text)
        self.assertIn("admin", text)
        self.assertEqual(found, 1)

    def test_a_whole_private_key_is_hidden(self):
        key = "-----BEGIN RSA PRIVATE KEY-----\n+MIIEabc\n+def\n-----END RSA PRIVATE KEY-----"
        text, found = hide_secrets(f"+{key}\n+next line")
        self.assertNotIn("MIIEabc", text)
        self.assertIn("next line", text)
        self.assertEqual(found, 1)

    def test_a_private_key_with_no_end_is_hidden_to_the_end(self):
        text, _ = hide_secrets("-----BEGIN PRIVATE KEY-----\nMIIEabc\ndef")
        self.assertEqual(text, HIDDEN)

    def test_ordinary_code_is_left_alone(self):
        for line in ("const token = getToken();", "password = request.form.password", 'password: process.env.DB_PASSWORD',
                     'const secret = "${SECRET_VALUE}"', "if (!password || password.length < 8) throw new Error('short');",
                     "const passwordHash = hash(password);", "token: tokenValue", "https://github.com/ada/shop/pull/4",
                     "@@ -1 +1 @@", "const a = 1;", 'pwd = ""', "tokens = countTokens(text)", ""):
            with self.subTest(line=line):
                self.assertEqual(hide_secrets(line), (line, 0))

    def test_no_text_is_safe(self):
        self.assertEqual(hide_secrets(None), ("", 0))


class TheModelNeverSeesASecret(AgentCase):
    def patch_with(self, patch, title="Add a payment client", filename="src/payments/client.ts"):
        self.fetch.return_value = ({**PR, "title": title}, [{"filename": filename, "additions": 3, "deletions": 0, "patch": patch}])
        self.script(reply("The createCharge client in src/payments/client.ts holds a key, so this payment code stays High.",
                          ["createCharge uses the key", "client rejects a missing key"]))

    def test_at38_a_secret_in_the_diff_is_not_in_the_prompt(self):
        self.patch_with(f"@@ -1 +1 @@\n+const key = '{AWS}';\n+const charge = createCharge(key);\n")
        result = self.run_agent()
        self.assertEqual(result["status"], "approved")
        prompt = self.first.prompts[0]
        self.assertNotIn(AWS, prompt)
        self.assertIn(HIDDEN, prompt)
        self.assertIn("createCharge", prompt, "the rest of the change must still be there to explain")

    def test_at38_a_secret_in_the_title_is_not_in_the_prompt(self):
        self.patch_with("@@ -1 +1 @@\n+const charge = createCharge();\n", title=f"Rotate key {GITHUB}")
        self.run_agent()
        self.assertNotIn(GITHUB, self.first.prompts[0])

    def test_at38_a_secret_cut_by_the_trim_is_still_hidden(self):
        padding = "+// " + "x" * 359 + "\n"  # puts the key across the 400 character cut, with its first 10 characters before it
        self.patch_with(f"@@ -1 +1 @@\n{padding}+const key = '{AWS}';\n")
        self.run_agent()
        for part in (AWS, AWS[:8]):
            self.assertNotIn(part, self.first.prompts[0])

    def test_at38_a_secret_stays_hidden_on_a_retry(self):
        self.patch_with(f"@@ -1 +1 @@\n+const key = '{AWS}';\n+const charge = createCharge(key);\n")
        self.script("not json", reply("The createCharge client in client.ts holds a key, so this stays High.", ["createCharge once", "key missing"]))
        self.assertEqual(self.run_agent()["attempts"], 2)
        self.assertEqual(len(self.first.prompts), 2)
        self.assertNotIn(AWS, "".join(self.first.prompts))

    def test_at38_the_label_comes_from_the_real_diff(self):
        patch = f"@@ -1 +1 @@\n+const password = 'hunter2hunter';\n+const token = '{AWS}';\n"
        self.fetch.return_value = (PR, [{"filename": "web/page.ts", "additions": 2, "deletions": 0, "patch": patch}])
        facts = analysis.score_pr(PR_ID, True)
        self.assertEqual(facts["risk_label"], "High")

    def test_at38_a_person_is_told_a_secret_was_found(self):
        self.patch_with(f"@@ -1 +1 @@\n+const key = '{AWS}';\n")
        facts = analysis.score_pr(PR_ID, True)
        notice = [f for f in facts["risk_factors"] if "possible secret" in f]
        self.assertEqual(len(notice), 1)
        self.assertNotIn(AWS, notice[0])

    def test_at38_a_change_with_no_secret_has_no_notice_and_is_unchanged(self):
        self.fetch.return_value = (PR, FILES)
        facts = analysis.score_pr(PR_ID, True)
        self.assertFalse(any("possible secret" in f for f in facts["risk_factors"]))
        self.assertNotIn(HIDDEN, facts["diff_summary"])
        self.assertIn(FILES[0]["patch"], facts["diff_summary"])

    def test_at38_the_placeholder_does_not_count_as_being_about_the_change(self):
        from agents import manager
        diff = f"src/x.ts (+1/-0)\n+const key = '{HIDDEN}';\n"
        self.assertFalse(manager.about_this_change("Some hidden secret was found in the payment flow.", diff))

    def test_at38_the_secret_is_not_kept_in_memory_for_the_prompt(self):
        self.patch_with(f"@@ -1 +1 @@\n+const key = '{AWS}';\n+const charge = createCharge(key);\n")
        self.run_agent()
        self.assertNotIn(AWS, ANALYSES[PR_ID]["facts"]["diff_summary"])


if __name__ == "__main__":
    unittest.main()
