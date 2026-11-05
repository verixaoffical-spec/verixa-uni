"""Regression tests for the bugs found while trying to break the app.

Every test here reproduced a real failure first: a crash, garbage that was stored, or a security gap. Each one runs
through the real app with a client that reports a crash as a 500 instead of raising it, the way an attacker sees it.
"""
import hashlib
import hmac
import json
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from backend.accounts import email_problem, name_problem, normalize_email, normalize_name, password_problem, safe_next
from backend.agent_db import AgentBase, RiskAssessment, init_agent_db
from backend.analysis_service import pr_facts
from backend.db import Project, SessionLocal, User
from backend.main import app
from backend.security import seal, valid_signature
from backend.settings import Settings, settings
from backend.validators import invalid_name_reason, scan, validate_collection, validate_spec

from .test_crud import PASSWORD, SCHEMA, CrudTestCase, count, row, spec
from .test_analysis_integration import PR_FILES, PR_INFO, approved_result, payload

GOOD_SPEC = "import { test, expect } from '@playwright/test';\ntest('t', async ({ page }) => { %s expect(1).toBe(1); });\n"
EVIL_ORIGIN = {"origin": "https://evil.example"}
XSS_NAME = "<img src=x onerror=alert(1)>"


def collection_of(*items):
    return json.dumps({"info": {"name": "API", "schema": SCHEMA}, "item": list(items)})


def request_to(url):
    return {"name": "r", "request": {"method": "GET", "url": url}}


class AttackCase(CrudTestCase):
    def setUp(self):
        AgentBase.metadata.drop_all(engine_of_tests())
        super().setUp()
        init_agent_db()

    def new_client(self) -> TestClient:
        client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
        client.__enter__()
        self.addCleanup(client.__exit__)
        return client

    def signed(self, body, event="pull_request"):
        raw = json.dumps(body).encode()
        signature = "sha256=" + hmac.new(settings.webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
        return self.client.post("/webhooks/github", content=raw,
                                headers={"x-hub-signature-256": signature, "x-github-event": event})

    def add_row(self, project_id, number=1, repo="ada/shop", **fields):
        with SessionLocal() as db:
            db.add(RiskAssessment(project_id=project_id, repo=repo, pr_number=number, head_sha=f"sha{number}",
                                  **{"state": "scored", "risk_label": "High", **fields}))
            db.commit()

    def project_id(self, uid):
        with SessionLocal() as db:
            return db.scalar(select(Project.id).where(Project.user_id == uid))


def engine_of_tests():
    from backend.db import engine
    return engine


# ---------- garbage values ----------

class GarbageInputTests(unittest.TestCase):
    def test_emails_carrying_code_or_junk_are_refused(self):
        for email in ("<script>alert(1)</script>@evil.com", '"><img/src=x/onerror=alert(1)>@x.com', "a\x00b@x.com",
                      "javascript:alert(1)@x.com", "a;b@x.com", "a@b.c0m", "a@-b.com", "a@b-.com", ".a@b.com", "a.@b.com",
                      "a@b.com,c@d.com", "a b@x.com", "a@x.com\r\nBcc:z@y.com", "(a)@x.com"):
            self.assertIsNotNone(email_problem(normalize_email(email)), repr(email))

    def test_real_emails_still_work(self):
        for email in ("a@b.co", "first.last+tag@sub.company.io", "x_y-z@domain.travel", "o'brien@example.com",
                      "ok.user+tag@example.co.uk", "me@xn--80ak6aa92e.xn--p1ai", "user123@123.example.org"):
            self.assertIsNone(email_problem(normalize_email(email)), email)

    def test_names_that_are_not_names_are_refused(self):
        for name in ("javascript:alert(1)", '" onmouseover="alert(1)', "'; DROP TABLE users;--", "12345", "!!!!!", "x",
                     "{{7*7}}", "${alert(1)}", "%3Cscript%3E", "<b>Ada</b>", "---", "...", "Ada\x00", "a‮b", "Ada(1)"):
            self.assertIsNotNone(name_problem(normalize_name(name)), repr(name))

    def test_real_names_still_work(self):
        for name in ("Ada Lovelace", "Zoë O'Brien-Smith", "李小龙", "José María", "Martin Luther King Jr.", "محمد علي", "O’Neil"):
            self.assertIsNone(name_problem(normalize_name(name)), name)

    def test_passwords_of_almost_one_repeated_character_are_refused(self):
        for password in ("aaaaaaa1", "a1a1a1a1", "ab1ab1ab1", "111111a1"):
            self.assertIsNotNone(password_problem(password), password)
        self.assertIsNone(password_problem("correct horse 9"))

    def test_file_names_that_hide_their_real_name_are_refused(self):
        for name in ("a‮gnp.spec.ts", "a\x7f.spec.ts", "a​b.spec.ts", "a﻿.spec.ts", "a\x85.spec.ts"):
            self.assertIsNotNone(invalid_name_reason(name), repr(name))

    def test_file_names_with_nothing_before_the_extension_are_refused(self):
        for name in ("..spec.ts", "...spec.ts", ". .spec.ts"):
            self.assertTrue(validate_spec(name, GOOD_SPEC % "")["errors"], name)
        for name in (".json", "..json"):
            self.assertTrue(validate_collection(name, collection_of(request_to("http://x/y")))["errors"], name)

    def test_redirect_after_sign_in_cannot_loop_back_to_login(self):
        self.assertEqual(safe_next("/login#x", "/APP"), "/APP")
        self.assertEqual(safe_next("/signup#x", "/APP"), "/APP")


class SpecRuleTests(unittest.TestCase):
    def test_code_that_can_run_anything_is_refused(self):
        for code in ("eval('1');", "eval ('1');", "new Function('return 1')();", "require('child_process');",
                     "require('worker_threads');", "process.binding('fs');", "process.dlopen(a, b);"):
            errors = validate_spec("a.spec.ts", GOOD_SPEC % code)["errors"]
            self.assertTrue(any("not allowed" in e for e in errors), code)

    def test_playwright_calls_that_only_look_similar_are_allowed(self):
        for code in ("await page.$eval('a', e => e);", "await page.evaluate(() => 1);", "await page.$$eval('a', e => e);",
                     "const retrieval = 1;"):
            self.assertEqual(validate_spec("a.spec.ts", GOOD_SPEC % code)["errors"], [], code)

    def test_a_regular_expression_is_not_mistaken_for_broken_code(self):
        for code in ("await expect(page).toHaveTitle(/Bob's/);", "await expect(page).toHaveTitle(/[(]x/);",
                     'await expect(page).toHaveURL(/a"b/);', "await expect(page).toHaveURL(/https?:\\/\\/x/);",
                     "const r = /[/'\"]/g;"):
            self.assertEqual(validate_spec("a.spec.ts", GOOD_SPEC % code)["errors"], [], code)

    def test_division_is_still_division(self):
        self.assertTrue(scan("const a = 4 / 2; const b = a / 1;")[1])
        self.assertFalse(scan("const a = 4 / 2; foo(")[1])  # the second slash must not hide the open bracket


class WorstCaseSpeedTests(unittest.TestCase):
    """One upload must never be able to tie up the server. Each of these took minutes before the limit was added."""
    HEAD = GOOD_SPEC % ""
    SIZE = 500 * 1024 - 200

    def assert_quick(self, check):
        started = time.perf_counter()
        check()
        self.assertLess(time.perf_counter() - started, 5)

    def test_files_of_nothing_but_opening_slashes(self):
        for piece in ("/[", "/", "(/", "=/"):
            body = self.HEAD + "=" + piece * (self.SIZE // len(piece))
            self.assert_quick(lambda: validate_spec("a.spec.ts", body))

    def test_a_file_of_nothing_but_test_calls(self):
        body = self.HEAD + "test('a',x);" * (self.SIZE // 12)
        self.assert_quick(lambda: validate_spec("a.spec.ts", body))

    def test_line_numbers_are_still_right(self):
        body = "import { test } from '@playwright/test';\n\ntest('a', x);\n\n\ntest('b', x); test('c', x);\ntest('d', x);\n"
        self.assertEqual([t["line"] for t in validate_spec("a.spec.ts", body)["tests"]], [3, 6, 6, 7])

    def test_addresses_of_nothing_but_braces(self):
        for piece in ("{", "{{a", "{{a}"):
            text = json.dumps({"info": {"name": "n", "schema": SCHEMA},
                               "item": [{"name": "r", "request": piece * (4_000_000 // len(piece))}]})
            self.assert_quick(lambda: validate_collection("c.json", text))

    def test_a_slash_with_no_partner_does_not_hide_a_regular_expression_on_the_next_line(self):
        body = self.HEAD + "const a = /;\nconst b = /'/;\n"
        self.assertTrue(scan("x = /;\ny = /'/;\n")[1])
        self.assertEqual(validate_spec("a.spec.ts", body)["errors"], [])


class CollectionRuleTests(unittest.TestCase):
    def check(self, *items):
        return validate_collection("c.json", collection_of(*items))["errors"]

    def test_odd_json_types_are_answered_never_crash(self):
        for item in ({"name": {"a": 1}, "item": [request_to("http://x/y")]}, {"name": 5, "item": [request_to("http://x/y")]},
                     {**request_to("http://x/y"), "event": [{"listen": "test", "script": "abc"}]},
                     {**request_to("http://x/y"), "event": [{"listen": "test", "script": [1]}]},
                     {**request_to("http://x/y"), "name": ["a"]}):
            self.assertIsInstance(self.check(item), list, item)

    def test_dangerous_url_schemes_are_refused(self):
        for url in ("javascript:alert(1)", "JavaScript:alert(1)", " javascript:alert(1)", "file:///etc/passwd",
                    "data:text/html,<script>alert(1)</script>", "vbscript:x", "ftp://x/y"):
            self.assertTrue(any("not allowed" in e for e in self.check(request_to(url))), url)
            self.assertTrue(self.check({"name": "r", "request": url}), url)

    def test_text_that_is_not_a_url_is_refused(self):
        self.assertTrue(self.check(request_to("not a url at all !!!")))

    def test_real_urls_still_work(self):
        for url in ("https://x.io/a", "http://localhost:3000/a", "{{base}}/users", "{{base url}}/a", "example.com:8080/a",
                    "https://x.io/a?q=two words"):
            self.assertEqual(self.check(request_to(url)), [], url)


# ---------- secrets and configuration ----------

class ConfigurationTests(unittest.TestCase):
    OTHER = dict(github_client_id="", github_client_secret="", atlassian_client_id="", atlassian_client_secret="")
    LONG = "x" * 32

    def test_empty_or_short_secrets_stop_the_server_starting(self):
        for bad in ("", "   ", "short", "x" * 15):
            with self.assertRaises(ValidationError, msg=repr(bad)):
                Settings(secret_key=bad, webhook_secret=self.LONG, _env_file=None, **self.OTHER)
            with self.assertRaises(ValidationError, msg=repr(bad)):
                Settings(secret_key=self.LONG, webhook_secret=bad, _env_file=None, **self.OTHER)

    def test_good_secrets_and_a_tidy_public_url(self):
        made = Settings(secret_key=self.LONG, webhook_secret=self.LONG, public_url="https://a.b/", _env_file=None, **self.OTHER)
        self.assertEqual(made.public_url, "https://a.b")

    def test_non_ascii_signature_is_just_wrong(self):
        self.assertFalse(valid_signature(b"{}", "sha256=\xe9"))
        self.assertFalse(valid_signature(b"{}", "Ā"))


# ---------- through the real app ----------

class MalformedRequestTests(AttackCase):
    def test_lone_surrogate_is_a_422_not_a_crash(self):
        headers = {"content-type": "application/json"}
        for body in (b'{"email":"a@b.co","password":"\\ud800"}', b'{"email":"\\ud800@b.co","password":"x12345678"}'):
            self.assertEqual(self.client.post("/auth/login", content=body, headers=headers).status_code, 422)
        body = b'{"name":"\\ud800","email":"a@b.co","password":"x12345678a"}'
        self.assertEqual(self.client.post("/auth/signup", content=body, headers=headers).status_code, 422)

    def test_validation_errors_never_echo_what_was_sent(self):
        res = self.client.post("/auth/login", json={"email": "a@b.co", "password": "SECRETVALUE" * 60})
        self.assertEqual(res.status_code, 422)
        self.assertNotIn("SECRETVALUE", res.text)

    def test_non_ascii_webhook_signature_is_a_401(self):
        res = self.client.post("/webhooks/github", content=b"{}", headers={"x-hub-signature-256": "sha256=\xe9".encode("latin-1")})
        self.assertEqual(res.status_code, 401)

    def test_signed_webhook_of_the_wrong_shape_never_crashes(self):
        for body in ([], "text", 5, None):
            self.assertEqual(self.signed(body).status_code, 400, body)
        for body in ({"repository": "x"}, {"repository": {"full_name": {"a": 1}}}, {"repository": {"full_name": 5}},
                     {"action": ["opened"]}, {"action": {"a": 1}},
                     {"action": "opened", "pull_request": "x", "repository": {"full_name": "a/b"}}):
            self.assertEqual(self.signed(body).status_code, 202, body)

    def test_request_without_a_length_is_refused_so_the_size_limit_holds(self):
        res = self.client.post("/auth/login", content=iter([b'{"email":', b'"a@b.co"}']),
                               headers={"content-type": "application/json"})
        self.assertEqual(res.status_code, 411)

    def test_huge_numbers_are_a_422(self):
        self.signup()
        self.assertEqual(self.client.get("/api/analysis/pull-requests/99999999999999999999999").status_code, 422)
        self.assertEqual(self.client.delete("/api/library/specs/a.spec.ts?revision=99999999999999999999999").status_code, 422)

    def test_stored_script_in_signup_is_refused_and_nothing_is_saved(self):
        for name, email in ((XSS_NAME, "ok@example.com"), ("Ada Love", "<script>alert(1)</script>@evil.com")):
            self.assertEqual(self.signup(email, name).status_code, 422)
        self.assertEqual(count(User), 0)

    def test_rename_refuses_garbage(self):
        self.signup()
        for name in (XSS_NAME, "javascript:alert(1)", "12345"):
            self.assertEqual(self.client.post("/api/account/name", json={"name": name}).status_code, 422, name)
        self.assertEqual(self.session()["account"]["name"], "Ada Lovelace")


class WebhookFactsTests(unittest.TestCase):
    def test_wrong_types_give_no_facts_rather_than_a_crash(self):
        repo = {"full_name": "a/b"}
        for body in ({"pull_request": "x", "repository": repo, "number": 1}, {"pull_request": {"head": "x"}, "repository": repo, "number": 1},
                     {"pull_request": {"head": {"sha": 123}}, "repository": repo, "number": 1},
                     {"pull_request": {"head": {"sha": "abc"}}, "repository": "x", "number": 1},
                     {"pull_request": {"head": {"sha": "abc"}}, "repository": repo, "number": True},
                     {"pull_request": {"head": {"sha": "abc"}}, "repository": repo, "number": -1}):
            self.assertIsNone(pr_facts(body), body)

    def test_text_fields_of_the_wrong_type_or_with_nul_are_cleaned(self):
        body = payload()
        body["pull_request"].update(title=5, user="x")
        facts = pr_facts(body)
        self.assertIsNone(facts["title"])
        self.assertIsNone(facts["author"])
        body["pull_request"]["title"] = "a\x00b"
        self.assertEqual(pr_facts(body)["title"], "ab")

    def test_only_a_github_address_is_kept_as_the_link(self):
        for url in ("javascript:alert(1)", "data:text/html,x", "https://evil.example/x", "http://github.com/a", "https://github.com.evil.example/x"):
            body = payload()
            body["pull_request"]["html_url"] = url
            self.assertIsNone(pr_facts(body)["pr_url"], url)
        self.assertEqual(pr_facts(payload())["pr_url"], "https://github.com/ada/shop/pull/4")


class CrossSiteTests(AttackCase):
    def test_every_change_refuses_another_site(self):
        self.connected_user()
        calls = [("POST", "/api/connect", {"repo": "ada/shop", "project_key": "QA"}),
                 ("POST", "/api/library/apply", {"specs": [{"name": "o.spec.ts", "text": spec()}]}),
                 ("DELETE", "/api/library/specs/o.spec.ts", None), ("DELETE", "/api/library/collection", None),
                 ("POST", "/api/disconnect", None), ("POST", "/api/analysis/analyse", {"pr_number": 1}),
                 ("POST", "/api/account/name", {"name": "Evil Name"}), ("POST", "/auth/logout", None)]
        for method, path, body in calls:
            res = self.client.request(method, path, json=body, headers=EVIL_ORIGIN)
            self.assertEqual(res.status_code, 403, path)
        self.assertEqual(self.session()["specs"], [])
        self.assertEqual(self.session()["account"]["name"], "Ada Lovelace")

    def test_the_same_requests_work_from_this_site(self):
        self.connected_user()
        body = {"specs": [{"name": "o.spec.ts", "text": spec()}]}
        res = self.client.post("/api/library/apply", json=body, headers={"origin": "http://testserver"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.client.delete("/api/library/specs/o.spec.ts", headers={"origin": "http://testserver"}).status_code, 204)


class ConnectTests(AttackCase):
    def test_path_tricks_never_reach_github(self):
        self.linked_user()
        for repo in ("../..", "a/..", "../b", ".../...", "./.", "a/.", "é/b"):
            self.fakes["ensure_webhook"].reset_mock()
            self.assertEqual(self.client.post("/api/connect", json={"repo": repo, "project_key": "QA"}).status_code, 422, repo)
            self.fakes["ensure_webhook"].assert_not_called()

    def test_real_repository_names_still_connect(self):
        self.linked_user()
        for repo in ("ada/shop", "ada-b/my.repo_1", "a/.github"):
            self.assertEqual(self.client.post("/api/connect", json={"repo": repo, "project_key": "QA"}).status_code, 200, repo)


class UnreadableSecretTests(AttackCase):
    """Rows encrypted under another key exist in the shared database (see the README), so this really happens."""

    def setUp(self):
        super().setUp()
        self.uid = self.connected_user()

    def spoil(self, **fields):
        with SessionLocal() as db:
            user = db.get(User, self.uid)
            for name, value in fields.items():
                setattr(user, name, value)
            db.commit()

    def test_github_routes_answer_with_a_way_forward(self):
        self.spoil(github_token="not-a-real-token")
        for res in (self.client.get("/api/targets"), self.client.post("/api/connect", json={"repo": "ada/shop", "project_key": "QA"})):
            self.assertEqual(res.status_code, 409, res.text)
            self.assertIn("again", res.json()["detail"])

    def test_disconnect_and_delete_still_work(self):
        self.spoil(github_token="not-a-real-token")
        self.assertEqual(self.client.post("/api/disconnect").status_code, 204)
        self.assertEqual(count(Project), 0)
        res = self.client.post("/api/account/delete", json={"password": PASSWORD})
        self.assertEqual(res.status_code, 204, res.text)
        self.assertEqual(count(User), 0)

    def test_two_step_code_is_not_a_crash(self):
        self.spoil(totp_secret="not-a-real-token")
        fresh = self.new_client()
        self.assertEqual(fresh.post("/auth/login", json={"email": "ada@example.com", "password": PASSWORD}).json(), {"two_factor": True})
        self.assertEqual(fresh.post("/auth/2fa/verify", json={"code": "123456"}).status_code, 409)


class RevokedTokenTests(AttackCase):
    """GitHub refusing a saved token used to answer 401, which the dashboard reads as a lost session: it went to log in,
    log in saw a good session and came straight back, for ever."""

    def setUp(self):
        super().setUp()
        self.uid = self.linked_user()

    def test_a_token_github_refuses_is_not_a_lost_session(self):
        github_says = httpx.Response(401, json={"message": "Bad credentials"})
        with mock.patch("backend.integrations.httpx.request", return_value=github_says):
            res = self.client.get("/api/targets")
        self.assertEqual(res.status_code, 409, res.text)
        self.assertIn("again", res.json()["detail"])
        self.assertIsNotNone(self.session()["account"])

    def test_an_answer_that_is_not_json_is_a_502(self):
        with mock.patch("backend.integrations.httpx.request", return_value=httpx.Response(200, text="<html>down</html>")):
            self.assertEqual(self.client.get("/api/targets").status_code, 502)

    def test_link_again_forgets_the_tokens_so_the_person_can_approve_again(self):
        self.assertEqual(self.client.post("/auth/relink", headers=EVIL_ORIGIN).status_code, 403)
        self.assertIsNotNone(self.session()["github"])
        self.assertEqual(self.client.post("/auth/relink").status_code, 204)
        session = self.session()
        self.assertIsNone(session["github"])
        self.assertIsNone(session["atlassian"])
        self.assertEqual(session["account"]["email"], "ada@example.com")
        self.assertIn("github.com/login/oauth", self.client.get("/auth/start").headers["location"])

    def test_link_again_needs_an_account(self):
        self.assertEqual(self.new_client().post("/auth/relink").status_code, 401)


class HeaderTests(AttackCase):
    def test_every_page_forbids_scripts_from_anywhere_else(self):
        for path in ("/", "/login", "/api/session"):
            policy = self.client.get(path).headers.get("content-security-policy", "")
            self.assertIn("script-src 'self'", policy, path)
            self.assertNotIn("unsafe-eval", policy)
            self.assertNotIn("'unsafe-inline' https://fonts.googleapis.com; script", policy)
            self.assertIn("object-src 'none'", policy)
            self.assertIn("frame-ancestors 'none'", policy)

    def test_built_pages_have_no_inline_script_the_policy_would_block(self):
        for path in ("/", "/login"):
            html = self.client.get(path).text
            self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)[^>]*>", path)

    def test_personal_answers_are_never_cached(self):
        self.signup()
        for path in ("/api/session", "/auth/2fa"):
            self.assertEqual(self.client.get(path).headers.get("cache-control"), "no-store", path)

    def test_files_outside_the_frontend_cannot_be_read(self):
        for path in ("/.env", "/.git/config", "/%2e%2e/backend/main.py", "/..%2f..%2f.env", "/assets/../../backend/settings.py",
                     "/VERIXA_PROTOTYPE.html", "/verixa_prototype.html.", "/verixa_prototype.html::$DATA"):
            self.assertEqual(self.client.get(path).status_code, 404, path)


class SignupThrottleTests(AttackCase):
    def test_checking_which_emails_exist_is_throttled(self):
        self.signup()
        fresh = self.new_client()
        answers = [self.signup(client=fresh).status_code for _ in range(12)]
        self.assertEqual(answers[0], 409)
        self.assertEqual(answers[-1], 429)


class RiskFeedTests(AttackCase):
    def setUp(self):
        super().setUp()
        self.uid = self.connected_user()
        self.pid = self.project_id(self.uid)

    def feed(self, query=""):
        return self.client.get("/api/analysis/pull-requests" + query).json()

    def test_counts_do_not_depend_on_the_page_size(self):
        for number in range(1, 6):
            self.add_row(self.pid, number)
        got = self.feed("?limit=1")
        self.assertEqual(len(got["items"]), 1)
        self.assertEqual(got["counts"]["total"], 5)
        self.assertEqual(got["counts"]["High"], 5)

    def test_an_earlier_repository_does_not_leak_into_the_screen(self):
        self.add_row(self.pid, 1)
        self.add_row(self.pid, 99, repo="old/repo")
        got = self.feed()
        self.assertEqual([i["repo"] for i in got["items"]], ["ada/shop"])
        self.assertEqual(got["counts"]["total"], 1)

    def test_times_say_they_are_utc_so_a_new_row_is_not_hours_old(self):
        self.add_row(self.pid, 1)
        updated = datetime.fromisoformat(self.feed()["items"][0]["updated_at"])
        self.assertIsNotNone(updated.tzinfo)
        self.assertLess(abs(datetime.now(timezone.utc) - updated), timedelta(minutes=5))

    def test_only_a_whole_number_is_a_pull_request_number(self):
        for bad in (True, "4", "4x", 4.5, None, -1, 0, 10_000_001, [4]):
            self.assertEqual(self.client.post("/api/analysis/analyse", json={"pr_number": bad}).status_code, 422, bad)


class AnalysisStateTests(AttackCase):
    def setUp(self):
        super().setUp()
        self.uid = self.connected_user()
        self.fetch_pr = mock.patch("agents.analysis.fetch_pr", return_value=(PR_INFO, PR_FILES)).start()
        mock.patch("agents.analysis.count_fix_commits", return_value=0).start()
        mock.patch("agents.analysis.count_defects", return_value=0).start()
        from agents.analysis import ANALYSES, _CACHE
        self.addCleanup(ANALYSES.clear)
        self.addCleanup(_CACHE.clear)

    def test_a_crash_is_recorded_so_the_screen_stops_waiting(self):
        async def boom(*_):
            raise RuntimeError("model exploded")
        with mock.patch("backend.analysis_service._load_runner", return_value=boom):
            res = self.client.post("/api/analysis/analyse", json={"pr_number": 7})
        self.assertEqual(res.status_code, 500)
        self.assertNotIn("exploded", res.text)
        self.assertEqual(row(RiskAssessment, pr_number=7).state, "failed")
        self.assertEqual(self.client.get("/api/analysis/pull-requests").json()["counts"]["pending"], 0)

    def test_a_new_push_is_scored_from_the_new_diff(self):
        from agents.analysis import ANALYSES, score_pr
        seen = []

        async def manager(pr_id, token=None):
            facts = score_pr(pr_id, False, token)  # what the Analysis Agent does
            seen.append(facts["head_sha"])
            ANALYSES[pr_id] = {"facts": facts}
            return approved_result(pr_id, facts)

        with mock.patch("backend.analysis_service._load_runner", return_value=manager):
            self.assertEqual(self.signed(payload(sha="a" * 40)).status_code, 202)
            self.fetch_pr.return_value = ({**PR_INFO, "head": {"sha": "b" * 40}}, PR_FILES)
            self.assertEqual(self.signed(payload(action="synchronize", sha="b" * 40)).status_code, 202)
        self.assertEqual(seen, ["a" * 40, "b" * 40])

    def test_a_failed_rerun_does_not_keep_the_old_explanation(self):
        pid = self.project_id(self.uid)
        with SessionLocal() as db:
            db.add(RiskAssessment(project_id=pid, repo="ada/shop", pr_number=4, head_sha="a" * 40, state="scored",
                                  reasoning="old words", test_areas='["old"]', model_used="old-model"))
            db.commit()
        from backend.analysis_service import store_result
        with SessionLocal() as db:
            rid = db.scalar(select(RiskAssessment.id))
            store_result(db, rid, {"status": "needs_human_review", "attempts": 3, "errors": ["no"], "analysis": None}, None)
        kept = row(RiskAssessment, id=rid)
        self.assertEqual(kept.state, "needs_human_review")
        self.assertIsNone(kept.reasoning)
        self.assertIsNone(kept.model_used)


class LogoutTests(AttackCase):
    def test_a_copied_cookie_stops_working_after_logout(self):
        self.signup()
        stolen = self.new_client()
        stolen.cookies.set("session", self.client.cookies.get("session"))
        self.assertIsNotNone(self.session(stolen)["account"])
        self.assertEqual(self.client.post("/auth/logout").status_code, 204)
        self.assertIsNone(self.session(stolen)["account"])
        self.assertEqual(stolen.get("/api/analysis/pull-requests").status_code, 401)

    def test_logging_in_again_works_and_logout_without_a_session_is_fine(self):
        self.signup()
        self.client.post("/auth/logout")
        self.assertEqual(self.client.post("/auth/logout").status_code, 204)
        res = self.client.post("/auth/login", json={"email": "ada@example.com", "password": PASSWORD})
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(self.session()["account"])


class HeavySaveTests(AttackCase):
    def test_one_account_cannot_keep_the_server_busy_with_saves(self):
        self.connected_user()
        answers = [self.apply(specs=[]).status_code for _ in range(22)]
        self.assertEqual(answers[0], 200)
        res = self.apply(specs=[])
        self.assertEqual(res.status_code, 429)
        self.assertIsInstance(res.json()["detail"], str)  # the dashboard shows this text as it is
        self.assertIn("Retry-After", res.headers)

    def test_more_files_than_a_library_holds_are_refused_before_any_checking(self):
        self.connected_user()
        with mock.patch("backend.library.validate_spec") as check:
            res = self.apply(specs=[{"name": f"s{i}.spec.ts", "text": spec()} for i in range(51)])
        self.assertEqual(res.status_code, 422)
        check.assert_not_called()


class AgentGitHubTests(unittest.TestCase):
    def test_no_token_means_no_authorization_header(self):
        from agents.github_client import _headers
        with mock.patch.dict("os.environ", {"GITHUB_TOKEN": ""}):
            self.assertNotIn("Authorization", _headers())
            self.assertEqual(_headers("abc")["Authorization"], "Bearer abc")


class ManagerGroundingTests(unittest.TestCase):
    """The replies here are real: the model wrote them about a pull request that only bumps a linter version."""
    PR = "psf/requests#7616"
    DIFF = (".pre-commit-config.yaml (+1/-1)\n@@ -13,7 +13,7 @@ repos:\n     args: [--fix=auto]\n   - id: trailing-whitespace\n"
            " - repo: https://github.com/astral-sh/ruff-pre-commit\n-  rev: v0.16.3\n+  rev: v0.16.4\n   hooks:\n     - id: ruff-check\n")
    AREAS = ["Follow redirect to same host with different path succeeds", "True redirect loop raises TooManyRedirects"]

    def run_validate(self, reasoning, areas=None, diff=None):
        from agents import manager
        reply = json.dumps({"reasoning": reasoning, "suggested_test_areas": areas or self.AREAS})
        state = {self.PR: {"raw": reply, "facts": {"risk_label": "Medium", "diff_summary": self.DIFF if diff is None else diff}}}
        with mock.patch.dict(manager.ANALYSES, state):
            return manager.validate(self.PR)

    def test_an_explanation_of_some_other_change_is_rejected(self):
        for reasoning in ("The change modifies the redirect-loop detection logic in the core request handling to compare full URLs "
                          "instead of just the host, affecting request flow and error handling.",
                          "This PR bumps requests to the next patch release, updating dependencies and adjusting the HTTPAdapter "
                          "to accommodate urllib3 2.0 and its HTTP/2 support."):
            data, errors = self.run_validate(reasoning)
            self.assertIsNone(data)
            self.assertTrue(any("changed code" in e for e in errors), errors)

    def test_an_explanation_of_this_change_is_accepted(self):
        for reasoning in ("This bumps the ruff-pre-commit hook from v0.16.3 to v0.16.4 in the pre-commit configuration.",
                          "Only the linter revision moves, in .pre-commit-config.yaml, so the risk comes from the config rule."):
            data, errors = self.run_validate(reasoning, ["ruff-check still passes on the repository", "bad revision fails the hook"])
            self.assertEqual(errors, [], reasoning)
            self.assertIsNotNone(data)

    def test_a_change_with_nothing_to_compare_is_not_rejected(self):
        self.assertEqual(self.run_validate("Nothing was changed in this pull request at all.", diff="")[1], [])

    def test_the_writer_only_sees_its_instructions(self):
        from agents.analysis import analysis_agent
        self.assertTrue(analysis_agent.writers)
        self.assertTrue(all(w.include_contents == "none" for w in analysis_agent.writers))


class SeedDemoTests(unittest.TestCase):
    def test_it_refuses_any_database_but_sqlite(self):
        from scripts import seed_demo
        with mock.patch.object(seed_demo, "engine") as engine, mock.patch.object(seed_demo, "init_db") as init:
            engine.dialect.name = "postgresql"
            with self.assertRaises(SystemExit):
                seed_demo.main()
            init.assert_not_called()


class OtherAccountTests(AttackCase):
    def test_one_account_cannot_see_or_touch_another(self):
        uid = self.connected_user()
        self.add_row(self.project_id(uid), 1)
        with SessionLocal() as db:
            assessment = db.scalar(select(RiskAssessment.id))
        self.assertEqual(self.apply(specs=[{"name": "mine.spec.ts", "text": spec()}]).status_code, 200)

        other = self.new_client()
        self.connected_user("eve@example.com", "eve/shop", client=other)
        self.assertEqual(other.get(f"/api/analysis/pull-requests/{assessment}").status_code, 404)
        self.assertEqual(other.get("/api/analysis/pull-requests").json()["items"], [])
        self.assertEqual(self.session(other)["specs"], [])
        self.assertEqual(other.delete("/api/library/specs/mine.spec.ts").status_code, 204)  # nothing of hers by that name
        self.assertEqual(len(self.session()["specs"]), 1)

    def test_tampered_session_cookie_is_ignored(self):
        self.signup()
        cookie = self.client.cookies.get("session")
        forged = self.new_client()
        forged.cookies.set("session", cookie[:-3] + "abc")
        self.assertEqual(forged.get("/api/analysis/pull-requests").status_code, 401)
        self.assertIsNone(forged.get("/api/session").json()["account"])


if __name__ == "__main__":
    unittest.main()
