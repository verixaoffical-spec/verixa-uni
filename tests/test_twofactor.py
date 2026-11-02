"""Two-step verification, end to end through the real app. Needs the built frontend (npm run build)."""
import time
import unittest
import urllib.parse as up
from contextlib import contextmanager
from unittest import mock

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend import auth, twofactor
from backend.accounts import hash_password
from backend.db import Base, RecoveryCode, SessionLocal, User, engine, init_db
from backend.main import app
from backend.security import unseal_totp
from backend.totp import STEP, match_step, new_recovery_codes, normalize_recovery, setup_details

APP = "/verixa_prototype.html"
EMAIL, PASSWORD = "ada@example.com", "correct horse 9"
THROTTLES = (auth.login_by_email, auth.login_by_ip, auth.signup_by_ip,
             twofactor.code_by_user, twofactor.code_by_ip, twofactor.password_by_user)


def code(secret: str, steps: int = 0) -> str:
    """The app's code for now, or for a later 30 second step."""
    return pyotp.TOTP(secret).at(time.time() + steps * STEP)


@contextmanager
def later(seconds: float):
    """Moves the clock forward."""
    real = time.time
    with mock.patch("time.time", lambda: real() + seconds):
        yield


class TotpTests(unittest.TestCase):
    secret = pyotp.random_base32()

    def test_accepts_the_current_step_and_one_either_side(self):
        now = int(time.time() // STEP)
        for steps in (-1, 0, 1):
            self.assertEqual(match_step(self.secret, code(self.secret, steps)), now + steps)

    def test_refuses_older_or_newer_codes(self):
        for steps in (-3, -2, 2, 3):
            self.assertIsNone(match_step(self.secret, code(self.secret, steps)))

    def test_refuses_anything_that_is_not_six_digits(self):
        good = code(self.secret)
        for bad in ("", "12345", "1234567", "abcdef", good[:5] + "x", None):
            self.assertIsNone(match_step(self.secret, bad), bad)
        self.assertIsNotNone(match_step(self.secret, f" {good[:3]} {good[3:]} "))

    def test_setup_details(self):
        details = setup_details(self.secret, EMAIL)
        self.assertTrue(details["qr"].startswith("data:image/svg+xml"))
        self.assertEqual(details["secret"].replace(" ", ""), self.secret)

    def test_recovery_codes(self):
        codes = new_recovery_codes()
        self.assertEqual(len(codes), 10)
        self.assertEqual(len(set(codes)), 10)
        for c in codes:
            self.assertRegex(c, r"^[a-z2-9]{5}-[a-z2-9]{5}$")
        self.assertEqual(normalize_recovery(" ABCDE fghjk "), "abcdefghjk")
        self.assertEqual(normalize_recovery("abcde-fghjk"), "abcdefghjk")


class AppTestCase(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        init_db()
        for t in THROTTLES:
            t._fails.clear()
        with SessionLocal() as db:
            db.add(User(email=EMAIL, name="Ada Lovelace", password_hash=hash_password(PASSWORD)))
            db.commit()
        self.client = self.new_client()

    def new_client(self) -> TestClient:
        client = TestClient(app, follow_redirects=False)
        client.__enter__()
        self.addCleanup(client.__exit__)
        return client

    def login(self, client=None):
        return (client or self.client).post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

    def verify(self, value, client=None):
        return (client or self.client).post("/auth/2fa/verify", json={"code": value})

    def account(self, client=None):
        return (client or self.client).get("/api/session").json()["account"]

    def turn_on(self):
        """Signs in and turns two-step verification on. Returns the secret and recovery codes."""
        self.assertEqual(self.login().status_code, 200)
        res = self.client.post("/auth/2fa/setup", json={"password": PASSWORD})
        self.assertEqual(res.status_code, 200, res.text)
        secret = res.json()["secret"].replace(" ", "")
        res = self.client.post("/auth/2fa/enable", json={"code": code(secret)})
        self.assertEqual(res.status_code, 200, res.text)
        return secret, res.json()["recovery_codes"]

    def user(self) -> User:
        with SessionLocal() as db:
            return db.scalar(select(User).where(User.email == EMAIL))


class WithoutTwoFactorTests(AppTestCase):
    def test_login_works_as_before(self):
        res = self.login()
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["account"]["two_factor"])
        self.assertEqual(self.account()["email"], EMAIL)
        self.assertEqual(self.client.get(APP).status_code, 200)

    def test_verify_without_a_password_step(self):
        self.assertEqual(self.verify("123456").status_code, 401)
        self.login()
        self.assertEqual(self.verify("123456").status_code, 401)  # signed in, but no code was asked for
        self.assertIsNotNone(self.account())  # and that did not sign the person out


class SetupTests(AppTestCase):
    def test_settings_need_a_session(self):
        self.assertEqual(self.client.get("/auth/2fa").status_code, 401)
        self.assertEqual(self.client.post("/auth/2fa/setup", json={"password": PASSWORD}).status_code, 401)
        self.assertEqual(self.client.post("/auth/2fa/enable", json={"code": "123456"}).status_code, 401)
        self.assertEqual(self.client.post("/auth/2fa/disable", json={"password": PASSWORD, "code": "1"}).status_code, 401)
        self.assertEqual(self.client.post("/auth/2fa/recovery-codes", json={"password": PASSWORD, "code": "1"}).status_code, 401)

    def test_setup_needs_the_password(self):
        self.login()
        res = self.client.post("/auth/2fa/setup", json={"password": "wrong password 1"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["detail"]["field"], "password")
        self.assertIsNone(self.user().totp_pending)

    def test_wrong_passwords_lock_settings(self):
        self.login()
        for _ in range(4):
            self.assertEqual(self.client.post("/auth/2fa/setup", json={"password": "wrong 1"}).status_code, 400)
        self.assertEqual(self.client.post("/auth/2fa/setup", json={"password": "wrong 1"}).status_code, 429)
        self.assertEqual(self.client.post("/auth/2fa/setup", json={"password": PASSWORD}).status_code, 429)

    def test_turning_on(self):
        self.login()
        res = self.client.post("/auth/2fa/setup", json={"password": PASSWORD})
        self.assertEqual(res.headers["cache-control"], "no-store")
        secret = res.json()["secret"].replace(" ", "")
        self.assertTrue(res.json()["qr"].startswith("data:image/svg+xml"))

        self.assertEqual(self.client.post("/auth/2fa/enable", json={"code": "000000"}).status_code, 400)
        self.assertFalse(self.client.get("/auth/2fa").json()["enabled"])

        res = self.client.post("/auth/2fa/enable", json={"code": code(secret)})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()["recovery_codes"]), 10)
        self.assertTrue(res.json()["account"]["two_factor"])
        self.assertEqual(self.client.get("/auth/2fa").json(), {"enabled": True, "has_password": True, "recovery_codes_left": 10})
        self.assertEqual(self.account()["email"], EMAIL)  # the session that turned it on stays signed in

    def test_secret_and_recovery_codes_are_not_stored_in_plain_text(self):
        secret, codes = self.turn_on()
        user = self.user()
        self.assertNotIn(secret, user.totp_secret)
        self.assertEqual(unseal_totp(user.totp_secret), secret)
        self.assertIsNone(user.totp_pending)
        with SessionLocal() as db:
            hashes = db.scalars(select(RecoveryCode.code_hash)).all()
        self.assertEqual(len(hashes), 10)
        for c in codes:
            self.assertFalse(any(normalize_recovery(c) in h for h in hashes))

    def test_secret_is_not_in_the_session_cookie(self):
        self.login()
        secret = self.client.post("/auth/2fa/setup", json={"password": PASSWORD}).json()["secret"].replace(" ", "")
        import base64
        cookie = self.client.cookies.get("session")
        payload = base64.b64decode(cookie.split(".")[0] + "==").decode()
        self.assertNotIn(secret, payload)

    def test_enable_needs_setup_first(self):
        self.login()
        res = self.client.post("/auth/2fa/enable", json={"code": "123456"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["detail"]["field"], "setup")

    def test_setup_times_out(self):
        self.login()
        secret = self.client.post("/auth/2fa/setup", json={"password": PASSWORD}).json()["secret"].replace(" ", "")
        with later(11 * 60):
            res = self.client.post("/auth/2fa/enable", json={"code": code(secret)})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["detail"]["field"], "setup")

    def test_turning_on_signs_out_other_sessions(self):
        other = self.new_client()
        self.login(other)
        self.assertIsNotNone(self.account(other))
        self.turn_on()
        self.assertIsNone(self.account(other))
        self.assertIsNotNone(self.account())

    def test_cannot_turn_on_twice(self):
        self.turn_on()
        self.assertEqual(self.client.post("/auth/2fa/setup", json={"password": PASSWORD}).status_code, 409)


class LoginWithTwoFactorTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.secret, self.codes = self.turn_on()
        self.client.post("/auth/logout")

    def test_password_alone_does_not_sign_in(self):
        res = self.login()
        self.assertEqual(res.json(), {"two_factor": True})
        self.assertIsNone(self.account())
        self.assertEqual(self.client.get("/api/targets").status_code, 401)
        self.assertEqual(self.client.get("/auth/2fa").status_code, 401)
        self.assertEqual(self.client.post("/auth/2fa/setup", json={"password": PASSWORD}).status_code, 401)
        res = self.client.get(APP)
        self.assertEqual(res.status_code, 307)
        self.assertTrue(res.headers["location"].startswith("/login"))
        self.assertEqual(self.client.get("/login").status_code, 200)  # the code step is still on the log in page

    def test_wrong_code(self):
        self.login()
        res = self.verify("000000")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["detail"]["field"], "code")
        self.assertIsNone(self.account())

    def test_right_code_signs_in(self):
        self.login()
        res = self.verify(code(self.secret, 1))  # the current step was used to turn it on
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIsNone(res.json()["recovery_codes_left"])
        self.assertEqual(self.account()["email"], EMAIL)
        self.assertEqual(self.client.get(APP).status_code, 200)

    def test_a_code_works_only_once(self):
        value = code(self.secret, 1)
        self.login()
        self.assertEqual(self.verify(value).status_code, 200)
        self.client.post("/auth/logout")
        self.login()
        self.assertEqual(self.verify(value).status_code, 400)
        self.assertIsNone(self.account())

    def test_an_older_code_is_refused_after_a_newer_one(self):
        with later(STEP):
            self.login()
            self.assertEqual(self.verify(code(self.secret, 1)).status_code, 200)
            self.client.post("/auth/logout")
            self.login()
            self.assertEqual(self.verify(code(self.secret, 0)).status_code, 400)  # still in the window, but older

    def test_pending_sign_in_expires(self):
        self.login()
        with later(auth.PENDING_SECONDS + 1):
            res = self.verify(code(self.secret, 1))
        self.assertEqual(res.status_code, 401)
        self.assertIn("timed out", res.json()["detail"])
        self.assertIsNone(self.account())

    def test_too_many_wrong_codes_lock_the_account(self):
        self.login()
        for _ in range(4):
            self.assertEqual(self.verify("000000").status_code, 400)
        res = self.verify("000000")
        self.assertEqual(res.status_code, 429)
        self.assertGreater(int(res.headers["retry-after"]), 0)
        self.assertEqual(self.verify(code(self.secret, 1)).status_code, 429)  # even the right code
        other = self.new_client()  # a new session does not reset the count
        self.login(other)
        self.assertEqual(self.verify(code(self.secret, 1), other).status_code, 429)
        self.assertIsNone(self.account())

    def test_lock_lifts_after_the_window(self):
        self.login()
        for _ in range(5):
            self.verify("000000")
        with mock.patch("time.monotonic", lambda real=time.monotonic: real() + 15 * 60 + 1):
            self.assertEqual(self.verify(code(self.secret, 1)).status_code, 200)

    def test_recovery_code(self):
        self.login()
        typed = " " + self.codes[0].upper().replace("-", " ") + " "  # as someone might type it from paper
        res = self.verify(typed)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["recovery_codes_left"], 9)
        self.assertIsNotNone(self.account())

        self.client.post("/auth/logout")
        self.login()
        self.assertEqual(self.verify(self.codes[0]).status_code, 400)  # single use
        self.assertEqual(self.verify("abcde-fghjk").status_code, 400)
        self.assertIsNone(self.account())

    def test_cross_site_request_is_refused(self):
        self.login()
        res = self.client.post("/auth/2fa/verify", json={"code": code(self.secret, 1)}, headers={"Origin": "https://evil.example"})
        self.assertEqual(res.status_code, 403)
        self.assertIsNone(self.account())


class ManageTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.secret, self.codes = self.turn_on()

    def confirm(self, path, password=PASSWORD, value=None):
        return self.client.post(path, json={"password": password, "code": value if value is not None else code(self.secret, 1)})

    def test_new_recovery_codes(self):
        self.assertEqual(self.confirm("/auth/2fa/recovery-codes", password="wrong 1").json()["detail"]["field"], "password")
        self.assertEqual(self.confirm("/auth/2fa/recovery-codes", value="000000").json()["detail"]["field"], "code")
        res = self.confirm("/auth/2fa/recovery-codes")
        self.assertEqual(res.status_code, 200)
        fresh = res.json()["recovery_codes"]
        self.assertEqual(len(fresh), 10)
        self.assertFalse(set(fresh) & set(self.codes))

        self.client.post("/auth/logout")
        self.login()
        self.assertEqual(self.verify(self.codes[1]).status_code, 400)  # the old codes stopped working
        self.assertEqual(self.verify(fresh[0]).status_code, 200)

    def test_turning_off(self):
        self.assertEqual(self.confirm("/auth/2fa/disable", password="wrong 1").status_code, 400)
        self.assertEqual(self.confirm("/auth/2fa/disable", value="000000").status_code, 400)
        self.assertTrue(self.client.get("/auth/2fa").json()["enabled"])

        res = self.confirm("/auth/2fa/disable", value=self.codes[0])  # a recovery code also works, for a lost phone
        self.assertEqual(res.status_code, 200, res.text)
        self.assertFalse(res.json()["account"]["two_factor"])
        user = self.user()
        self.assertIsNone(user.totp_secret)
        with SessionLocal() as db:
            self.assertEqual(db.scalars(select(RecoveryCode)).all(), [])

        self.client.post("/auth/logout")
        self.assertIn("account", self.login().json())  # back to a normal log in

    def test_settings_errors_never_look_like_a_lost_session(self):
        for res in (self.confirm("/auth/2fa/disable", password="wrong 1"), self.confirm("/auth/2fa/disable", value="000000")):
            self.assertEqual(res.status_code, 400)
        self.assertIsNotNone(self.account())


class GitHubTests(AppTestCase):
    def github_sign_in(self, client=None):
        client = client or self.client
        state = up.parse_qs(up.urlsplit(client.get("/auth/github").headers["location"]).query)["state"][0]
        me = {"id": 4242, "login": "ada-gh", "name": "Ada"}
        with mock.patch("backend.auth.github_exchange", return_value=("gh-token", me)):
            return client.get(f"/auth/github/callback?code=x&state={state}")

    def test_github_sign_in_asks_for_the_code(self):
        secret, _ = self.turn_on()
        with SessionLocal() as db:
            db.get(User, self.user().id).github_id = 4242
            db.commit()
        self.client.post("/auth/logout")

        res = self.github_sign_in()
        self.assertEqual(res.headers["location"], "/login?verify")
        self.assertIsNone(self.account())
        self.assertEqual(self.verify(code(secret, 1)).status_code, 200)
        self.assertEqual(self.account()["email"], EMAIL)

    def test_github_sign_in_without_two_factor_is_unchanged(self):
        res = self.github_sign_in()
        self.assertEqual(res.headers["location"], APP)
        self.assertEqual(self.account()["github_login"], "ada-gh")

    def test_account_without_password_must_have_signed_in_recently(self):
        self.github_sign_in()
        with later(twofactor.RECENT_SIGN_IN + 1):
            res = self.client.post("/auth/2fa/setup", json={"password": ""})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["detail"]["field"], "reauth")
        self.assertEqual(self.client.post("/auth/2fa/setup", json={"password": ""}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
