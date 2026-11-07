"""Forgot password, end to end through the real app. Needs the built frontend (npm run build)."""
import unittest
from datetime import timedelta
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend import auth, password_reset
from backend.accounts import hash_password, verify_password
from backend.db import Base, PasswordReset, SessionLocal, User, engine, init_db, now
from backend.main import app
from tests.test_twofactor import code

EMAIL, PASSWORD, NEW = "ada@example.com", "correct horse 9", "brand new pass 7"
THROTTLES = (auth.login_by_email, auth.login_by_ip, auth.signup_by_ip, password_reset.forgot_by_ip,
             password_reset.forgot_by_email, password_reset.reset_by_ip)


class ResetTestCase(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        init_db()
        for t in THROTTLES:
            t._fails.clear()
        with SessionLocal() as db:
            db.add(User(email=EMAIL, name="Ada Lovelace", password_hash=hash_password(PASSWORD)))
            db.commit()
        self.sent = []
        patcher = mock.patch.object(password_reset, "send_email", lambda to, subject, text: self.sent.append((to, text)))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = self.new_client()

    def new_client(self) -> TestClient:
        client = TestClient(app, follow_redirects=False)
        client.__enter__()
        self.addCleanup(client.__exit__)
        return client

    def forgot(self, email=EMAIL, client=None):
        return (client or self.client).post("/auth/forgot", json={"email": email})

    def token(self) -> str:
        """Asks for a link and returns the token from the email."""
        self.assertEqual(self.forgot().status_code, 202)
        link = self.sent[-1][1].split("#token=")[1].split()[0]
        return link

    def reset(self, token, password=NEW, client=None):
        return (client or self.client).post("/auth/reset", json={"token": token, "password": password})

    def login(self, password, client=None):
        return (client or self.client).post("/auth/login", json={"email": EMAIL, "password": password})

    def user(self) -> User:
        with SessionLocal() as db:
            return db.scalar(select(User).where(User.email == EMAIL))


class AskForLinkTests(ResetTestCase):
    def test_sends_one_link_to_the_account_email(self):
        res = self.forgot("  ADA@Example.com ")
        self.assertEqual(res.status_code, 202)
        self.assertEqual(len(self.sent), 1)
        to, text = self.sent[0]
        self.assertEqual(to, EMAIL)
        self.assertIn("/reset-password#token=", text)
        self.assertIn("Hi Ada Lovelace", text)

    def test_unknown_email_gets_the_same_answer_and_no_email(self):
        known, unknown = self.forgot(), self.forgot("nobody@example.com")
        self.assertEqual(unknown.status_code, known.status_code)
        self.assertEqual(unknown.json(), known.json())
        self.assertEqual(len(self.sent), 1)

    def test_bad_email_is_refused(self):
        res = self.forgot("not-an-email")
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.json()["detail"]["field"], "email")

    def test_only_a_hash_of_the_token_is_stored(self):
        token = self.token()
        with SessionLocal() as db:
            row = db.scalar(select(PasswordReset))
        self.assertNotEqual(row.token_hash, token)
        self.assertEqual(row.token_hash, password_reset.token_hash(token))

    def test_a_new_link_replaces_the_old_one(self):
        old, new = self.token(), self.token()
        self.assertEqual(self.reset(old).status_code, 400)
        self.assertEqual(self.reset(new).status_code, 200)

    def test_the_same_email_is_limited_to_3_links_an_hour(self):
        for _ in range(3):
            self.assertEqual(self.forgot().status_code, 202)
        res = self.forgot()
        self.assertEqual(res.status_code, 429)
        self.assertIn("Retry-After", res.headers)
        self.assertEqual(len(self.sent), 3)

    def test_requests_from_another_site_are_refused(self):
        res = self.client.post("/auth/forgot", json={"email": EMAIL}, headers={"Origin": "https://evil.example"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.sent, [])


class ChooseNewPasswordTests(ResetTestCase):
    def test_new_password_works_and_old_one_does_not(self):
        res = self.reset(self.token())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.login(PASSWORD).status_code, 401)
        self.assertEqual(self.login(NEW).status_code, 200)

    def test_a_link_works_only_once(self):
        token = self.token()
        self.assertEqual(self.reset(token).status_code, 200)
        self.assertEqual(self.reset(token, "another pass 8").status_code, 400)
        self.assertTrue(verify_password(NEW, self.user().password_hash))

    def test_an_expired_link_is_refused(self):
        token = self.token()
        with SessionLocal() as db:
            db.scalar(select(PasswordReset)).expires_at = now() - timedelta(seconds=1)
            db.commit()
        res = self.reset(token)
        self.assertEqual(res.status_code, 400)
        self.assertIn("expired", res.json()["detail"])
        self.assertTrue(verify_password(PASSWORD, self.user().password_hash))

    def test_made_up_or_empty_tokens_are_refused(self):
        self.token()
        for token in ("", "x" * 43, "a" * 200):
            self.assertEqual(self.reset(token).status_code, 400, token)
        self.assertTrue(verify_password(PASSWORD, self.user().password_hash))

    def test_weak_password_is_refused_and_the_link_still_works(self):
        token = self.token()
        res = self.reset(token, "password123")
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.json()["detail"]["field"], "password")
        res = self.reset(token, "adalovelace1")  # the name rule needs the account, so only the server can check it
        self.assertEqual(res.status_code, 422)
        self.assertEqual(self.reset(token).status_code, 200)

    def test_every_session_is_signed_out(self):
        other = self.new_client()
        self.assertEqual(self.login(PASSWORD, other).status_code, 200)
        self.assertEqual(other.get("/api/session").status_code, 200)
        self.assertIsNotNone(other.get("/api/session").json().get("account"))
        self.assertEqual(self.reset(self.token()).status_code, 200)
        self.assertIsNone(other.get("/api/session").json().get("account"))

    def test_clears_a_login_lockout(self):
        for _ in range(5):
            self.login("wrong password 1")
        self.assertEqual(self.login(PASSWORD).status_code, 429)
        self.assertEqual(self.reset(self.token()).status_code, 200)
        self.assertEqual(self.login(NEW).status_code, 200)

    def test_two_step_verification_still_asks_for_a_code(self):
        self.assertEqual(self.login(PASSWORD).status_code, 200)
        secret = self.client.post("/auth/2fa/setup", json={"password": PASSWORD}).json()["secret"].replace(" ", "")
        self.assertEqual(self.client.post("/auth/2fa/enable", json={"code": code(secret)}).status_code, 200)
        self.assertEqual(self.reset(self.token()).status_code, 200)
        res = self.login(NEW)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("two_factor"))
        self.assertIsNone(self.client.get("/api/session").json().get("account"))

    def test_too_many_bad_tokens_are_slowed_down(self):
        for _ in range(20):
            self.reset("y" * 43)
        self.assertEqual(self.reset("y" * 43).status_code, 429)

    def test_deleting_the_account_removes_its_links(self):
        self.token()
        self.assertEqual(self.login(PASSWORD).status_code, 200)
        res = self.client.post("/api/account/delete", json={"password": PASSWORD})
        self.assertEqual(res.status_code, 204, res.text)
        with SessionLocal() as db:
            self.assertIsNone(db.scalar(select(PasswordReset)))


class PageTests(ResetTestCase):
    def test_pages_are_served(self):
        for path in ("/forgot-password", "/reset-password"):
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, path)
            self.assertEqual(res.headers["cache-control"], "no-store")

    def test_reset_page_opens_even_when_signed_in(self):
        self.assertEqual(self.login(PASSWORD).status_code, 200)
        self.assertEqual(self.client.get("/forgot-password").status_code, 307)
        self.assertEqual(self.client.get("/reset-password").status_code, 200)


class MailerTests(unittest.TestCase):
    def test_without_smtp_the_email_is_printed_not_sent(self):
        from backend import mailer
        with mock.patch.object(mailer.settings, "smtp_host", ""), mock.patch("smtplib.SMTP") as smtp, \
                self.assertLogs("verixa.mail", "WARNING") as logs:
            mailer.send_email("ada@example.com", "Subject", "the link")
        smtp.assert_not_called()
        self.assertIn("the link", logs.output[0])

    def test_with_smtp_it_logs_in_and_sends(self):
        from backend import mailer
        with mock.patch.multiple(mailer.settings, smtp_host="smtp.example.com", smtp_port=587, smtp_user="me@example.com",
                                 smtp_password="app-pass", mail_from=""), mock.patch("smtplib.SMTP") as smtp:
            mailer.send_email("ada@example.com", "Subject", "the link")
        server = smtp.return_value
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("me@example.com", "app-pass")
        message = server.send_message.call_args.args[0]
        self.assertEqual(message["From"], "me@example.com")
        self.assertEqual(message["To"], "ada@example.com")

    def test_a_broken_mail_server_is_logged_not_raised(self):
        from backend import mailer
        with mock.patch.object(mailer.settings, "smtp_host", "smtp.example.com"), \
                mock.patch("smtplib.SMTP", side_effect=OSError("down")), self.assertLogs("verixa.mail", "ERROR"):
            mailer.send_email("ada@example.com", "Subject", "the link")


if __name__ == "__main__":
    unittest.main()
