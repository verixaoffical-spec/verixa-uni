"""GitHub tokens last 8 hours. These tests move the clock forward, through the real app, with only GitHub faked.

The fake behaves as GitHub's docs describe: using a refresh token stops it and the old access token from working.
"""
import asyncio
import threading
import time
import urllib.parse as up
from unittest import mock

import httpx
from sqlalchemy import select

from backend import analysis_service
from backend.agent_db import RiskAssessment
from backend.db import SessionLocal, User
from backend.integrations import GITHUB_TOKEN_URL, github_access_token
from backend.security import seal, unseal

from .test_analysis_integration import payload
from .test_crud import CrudTestCase

EIGHT_HOURS = 8 * 60 * 60
REAL_TIME = time.time


class FakeGitHub:
    """Hands out numbered tokens, and refuses any that were replaced."""

    def __init__(self):
        self.generation = 0
        self.valid_access = None
        self.valid_refresh = None
        self.refresh_calls = 0
        self.lock = threading.Lock()
        self.down = False

    def _issue(self):
        self.generation += 1
        self.valid_access, self.valid_refresh = f"gho_{self.generation}", f"ghr_{self.generation}"
        return httpx.Response(200, json={"access_token": self.valid_access, "refresh_token": self.valid_refresh, "expires_in": EIGHT_HOURS,
                                         "refresh_token_expires_in": 15897600, "token_type": "bearer", "scope": "repo"})

    def __call__(self, method, url, **kwargs):
        if url == GITHUB_TOKEN_URL:
            data = kwargs["data"]
            if data.get("grant_type") != "refresh_token":
                return self._issue()
            with self.lock:
                self.refresh_calls += 1
                time.sleep(0.02)  # long enough for a second request to arrive during a renewal
                if self.down:
                    return httpx.Response(503, text="unavailable")
                if data["refresh_token"] != self.valid_refresh or not data.get("client_secret"):
                    return httpx.Response(200, json={"error": "bad_refresh_token"})
                return self._issue()
        token = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        if token != self.valid_access:
            return httpx.Response(401, json={"message": "Bad credentials"})
        if url.endswith("/user"):
            return httpx.Response(200, json={"id": 77, "login": "ada", "name": "Ada"})
        if url.endswith("/user/repos"):
            return httpx.Response(200, json=[{"full_name": "ada/shop", "permissions": {"admin": True}}])
        return httpx.Response(404, json={})


class RefreshCase(CrudTestCase):
    def setUp(self):
        super().setUp()
        self.github_api = FakeGitHub()
        patcher = mock.patch("backend.integrations._call", side_effect=self.github_api)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.signup()
        self.link_github()

    def link_github(self):
        start = self.client.get("/auth/github")
        query = up.parse_qs(up.urlsplit(start.headers["location"]).query)
        self.authorize_query = query
        answer = self.client.get("/auth/github/callback", params={"code": "abc", "state": query["state"][0]})
        self.assertEqual(answer.status_code, 307, answer.text)
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "ada@example.com"))
            user.atlassian_token = seal("atl")
            db.commit()

    def row(self) -> User:
        with SessionLocal() as db:
            return db.scalar(select(User).where(User.email == "ada@example.com"))

    def after(self, hours):
        offset = hours * 3600
        patcher = mock.patch("time.time", side_effect=lambda: REAL_TIME() + offset)
        patcher.start()
        self.addCleanup(patcher.stop)
        return patcher

    def repos(self):
        return self.client.get("/api/targets")


class SavingTests(RefreshCase):
    def test_sign_in_asks_for_a_refresh_token(self):
        self.assertEqual(self.authorize_query["scope"], ["repo offline_access"])

    def test_tokens_are_saved_encrypted(self):
        user = self.row()
        self.assertNotIn("ghr_1", user.github_refresh)
        self.assertEqual(unseal(user.github_refresh), "ghr_1")
        self.assertNotIn("gho_1", user.github_token)

    def test_a_token_is_renewed_ten_minutes_early(self):
        self.assertAlmostEqual(self.row().github_expires_at, REAL_TIME() + EIGHT_HOURS - 600, delta=5)

    def test_link_again_forgets_everything(self):
        self.client.post("/auth/relink")
        user = self.row()
        self.assertIsNone(user.github_token)
        self.assertIsNone(user.github_refresh)
        self.assertIsNone(user.github_expires_at)


class AfterEightHoursTests(RefreshCase):
    def test_a_fresh_token_is_not_renewed(self):
        self.assertEqual(self.repos().status_code, 200)
        self.assertEqual(self.github_api.refresh_calls, 0)

    def test_after_nine_hours_it_just_works_without_link_again(self):
        self.after(9)
        answer = self.repos()
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(answer.json()["repos"], ["ada/shop"])
        self.assertEqual(self.github_api.refresh_calls, 1)
        self.assertEqual(unseal(self.row().github_token), "gho_2")

    def test_the_replaced_token_really_would_have_failed(self):
        """Proves the fake enforces expiry, so the test above means something."""
        self.after(9)
        self.repos()
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "ada@example.com"))
            user.github_token = seal("gho_1")
            user.github_expires_at = None
            db.commit()
        self.assertEqual(self.repos().status_code, 409)

    def test_it_keeps_working_day_after_day(self):
        for day, hours in enumerate(range(9, 9 * 12, 9), start=1):
            self.after(hours)
            answer = self.repos()
            self.assertEqual(answer.status_code, 200, f"renewal {day}: {answer.text}")
        self.assertEqual(self.github_api.refresh_calls, 11)
        self.assertEqual(unseal(self.row().github_refresh), "ghr_12")

    def test_the_login_session_does_not_end_during_this(self):
        self.after(9)
        self.assertIsNotNone(self.client.get("/api/session").json()["account"])

    def test_two_requests_at_once_renew_only_once(self):
        """A second renewal with the same refresh token would fail, and could lose the account's link."""
        self.after(9)
        results = []

        def work():
            with SessionLocal() as db:
                results.append(github_access_token(db, db.scalar(select(User).where(User.email == "ada@example.com"))))

        threads = [threading.Thread(target=work) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(self.github_api.refresh_calls, 1)
        self.assertEqual(results, ["gho_2"] * 5)


class EveryPathTests(RefreshCase):
    def connect(self):
        with mock.patch("backend.api._wait_for_delivery", return_value=True):
            answer = self.client.post("/api/connect", json={"repo": "ada/shop", "project_key": "QA"})
        self.assertEqual(answer.status_code, 200, answer.text)

    def test_webhook_scoring_gets_the_renewed_token(self):
        self.connect()
        self.after(9)
        seen = []

        async def score(row_id, pr_id, token):
            seen.append(token)

        with mock.patch("backend.analysis_service._score_one", side_effect=score):
            asyncio.run(analysis_service.analyse_pull_request(payload(repo="ada/shop"), "delivery-1"))
        self.assertEqual(seen, ["gho_2"])

    def test_analyse_now_gets_the_renewed_token(self):
        self.connect()
        self.after(9)
        seen = []

        async def now(project, number, token):
            seen.append(token)
            return None

        with mock.patch("backend.analysis_api.analyse_now", side_effect=now):
            self.client.post("/api/analysis/analyse", json={"pr_number": 4})
        self.assertEqual(seen, ["gho_2"])

    def test_connect_gets_the_renewed_token(self):
        self.after(9)
        self.connect()
        self.assertEqual(self.fakes["ensure_webhook"].call_args[0][0], "gho_2")

    def test_disconnect_gets_the_renewed_token(self):
        self.connect()
        self.after(9)
        self.assertLess(self.client.post("/api/disconnect").status_code, 300)
        self.assertEqual(self.fakes["delete_webhook"].call_args[0][0], "gho_2")

    def test_a_failed_renewal_on_a_webhook_keeps_the_row(self):
        self.connect()
        self.after(9)
        self.github_api.down = True
        seen = []

        async def score(row_id, pr_id, token):
            seen.append(token)

        with mock.patch("backend.analysis_service._score_one", side_effect=score):
            asyncio.run(analysis_service.analyse_pull_request(payload(repo="ada/shop"), "delivery-2"))
        self.assertEqual(seen, [None])
        with SessionLocal() as db:
            self.assertEqual(len(db.scalars(select(RiskAssessment)).all()), 1)


class WhenRenewalCannotWorkTests(RefreshCase):
    def test_a_refused_refresh_token_asks_to_link_again(self):
        self.after(9)
        self.github_api.valid_refresh = "something-else"
        answer = self.repos()
        self.assertEqual(answer.status_code, 409)
        self.assertIn("Link your account again", answer.json()["detail"])

    def test_link_again_fixes_a_refused_refresh_token(self):
        self.after(9)
        self.github_api.valid_refresh = "something-else"
        self.assertEqual(self.repos().status_code, 409)
        self.client.post("/auth/relink")
        self.link_github()
        self.assertEqual(self.repos().status_code, 200)

    def test_github_being_down_keeps_the_tokens_for_the_next_try(self):
        self.after(9)
        self.github_api.down = True
        self.assertEqual(self.repos().status_code, 502)
        self.assertEqual(unseal(self.row().github_refresh), "ghr_1")
        self.github_api.down = False
        self.assertEqual(self.repos().status_code, 200)

    def test_an_error_from_github_does_not_erase_the_session(self):
        self.after(9)
        self.github_api.valid_refresh = "something-else"
        self.repos()
        self.assertIsNotNone(self.client.get("/api/session").json()["account"])

    def test_an_older_token_with_no_expiry_still_works(self):
        """Accounts linked before this change. They get a refresh token at their next Link again."""
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "ada@example.com"))
            user.github_token, user.github_refresh, user.github_expires_at = seal(self.github_api.valid_access), None, None
            db.commit()
        self.after(9)
        self.assertEqual(self.repos().status_code, 200)
        self.assertEqual(self.github_api.refresh_calls, 0)

    def test_an_expired_token_without_a_refresh_token_asks_to_link_again(self):
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "ada@example.com"))
            user.github_refresh = None
            db.commit()
        self.after(9)
        self.assertEqual(self.repos().status_code, 409)

    def test_no_token_ever_appears_in_an_answer(self):
        self.after(9)
        text = self.repos().text + self.client.get("/api/session").text
        self.assertNotIn("gho_", text)
        self.assertNotIn("ghr_", text)
