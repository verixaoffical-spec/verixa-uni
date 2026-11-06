"""The Privacy Policy and Terms of Service are public pages, and their claims match the code."""
import unittest

from fastapi.testclient import TestClient

from backend.agent_db import RiskAssessment
from backend.db import User
from backend.main import app


class LegalPageTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_pages_are_public(self):
        for path, title in (("/privacy", "Privacy Policy"), ("/terms", "Terms of Service")):
            answer = self.client.get(path)
            self.assertEqual(answer.status_code, 200, path)
            self.assertIn(title, answer.text)
            self.assertIn("verixa.offical@gmail.com", answer.text)
            self.assertIn("Content-Security-Policy", answer.headers)

    def test_pages_run_no_script_so_the_security_policy_allows_them(self):
        for path in ("/privacy", "/terms"):
            self.assertNotIn("<script", self.client.get(path).text)

    def test_no_atlassian_account_id_is_stored(self):
        """The Privacy Policy promises this. If a column like it is added, the policy must change too."""
        columns = {c.name for c in User.__table__.columns} | {c.name for c in RiskAssessment.__table__.columns}
        self.assertFalse({"atlassian_account_id", "atlassian_id", "account_id"} & columns)

    def test_code_changes_are_not_stored(self):
        """The Privacy Policy promises this too."""
        columns = {c.name for c in RiskAssessment.__table__.columns}
        self.assertFalse({"diff", "patch", "diff_summary"} & columns)
