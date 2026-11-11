"""Every create, read, update and delete, end to end through the real app, checking the rows in the database.

GitHub and Jira calls are faked, everything else is real. Needs the built frontend (npm run build).
"""
import hashlib
import hmac
import json
import unittest
from unittest import mock

import pyotp
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend import api, auth, twofactor
from backend.accounts import hash_password
from backend.db import Base, Collection, Project, RecoveryCode, SessionLocal, SpecFile, User, engine, init_db
from backend.main import app, mark_verified
from backend.security import seal, seal_totp, unseal
from backend.settings import settings

PASSWORD = "correct horse 9"
SPEC = "import { test, expect } from '@playwright/test';\ntest('%s', async () => { expect(1).toBe(1); });\n"
SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
JIRA = [{"key": "QA", "name": "QA Board"}, {"key": "WEB", "name": "Website"}]


def spec(title="a"):
    return SPEC % title


def collection(*requests):
    items = [{"name": r, "request": {"method": "GET", "url": f"http://x/{r}"}} for r in requests or ("r",)]
    return json.dumps({"info": {"name": "API", "schema": SCHEMA}, "item": items})


def count(model, **where) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model).filter_by(**where))


def row(model, **where):
    with SessionLocal() as db:
        return db.scalar(select(model).filter_by(**where))


class CrudTestCase(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        init_db()
        for t in (auth.login_by_email, auth.login_by_ip, auth.signup_by_ip,
                  twofactor.code_by_user, twofactor.code_by_ip, twofactor.password_by_user, api.saves_by_user):
            t._fails.clear()
        self.client = self.new_client()
        # GitHub and Jira are faked. The ping calls the real code that runs when GitHub delivers it.
        self.github = {
            "list_jira_projects": mock.patch("backend.api.list_jira_projects", return_value=JIRA),
            "ensure_webhook": mock.patch("backend.api.ensure_webhook", return_value=111),
            "delete_webhook": mock.patch("backend.api.delete_webhook"),
            "ping_webhook": mock.patch("backend.api.ping_webhook", side_effect=lambda t, repo, h: mark_verified(repo)),
        }
        self.fakes = {name: p.start() for name, p in self.github.items()}
        self.addCleanup(mock.patch.stopall)

    def new_client(self) -> TestClient:
        client = TestClient(app, follow_redirects=False)
        client.__enter__()
        self.addCleanup(client.__exit__)
        return client

    def signup(self, email="ada@example.com", name="Ada Lovelace", password=PASSWORD, client=None):
        return (client or self.client).post("/auth/signup", json={"name": name, "email": email, "password": password})

    def linked_user(self, email="ada@example.com", client=None):
        """Signs up and links GitHub and Atlassian, as the OAuth callbacks would."""
        self.assertEqual(self.signup(email, client=client).status_code, 201)
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == email))
            user.github_token, user.atlassian_token = seal("gh-token"), seal("atl-token")
            user.github_login, user.jira_site = "ada", "ada.atlassian.net"
            db.commit()
            return user.id

    def connected_user(self, email="ada@example.com", repo="ada/shop", client=None):
        uid = self.linked_user(email, client)
        res = (client or self.client).post("/api/connect", json={"repo": repo, "project_key": "QA"})
        self.assertEqual(res.status_code, 200, res.text)
        return uid

    def apply(self, client=None, **body):
        return (client or self.client).post("/api/library/apply", json=body)

    def session(self, client=None):
        return (client or self.client).get("/api/session").json()


class AccountTests(CrudTestCase):
    def test_signup_stores_the_account(self):
        res = self.signup("  Ada@Example.COM ", "  Ada   Lovelace ")
        self.assertEqual(res.status_code, 201, res.text)
        user = row(User, email="ada@example.com")
        self.assertIsNotNone(user)
        self.assertEqual(user.name, "Ada Lovelace")
        self.assertIsNotNone(user.created_at)
        self.assertTrue(user.password_hash.startswith("scrypt$"))
        self.assertNotIn(PASSWORD, user.password_hash)
        self.assertEqual(self.session()["account"]["email"], "ada@example.com")

    def test_duplicate_email_is_refused(self):
        self.signup()
        res = self.signup("ADA@example.com", client=self.new_client())
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["detail"]["field"], "email")
        self.assertEqual(count(User), 1)

    def test_invalid_signups_store_nothing(self):
        cases = [
            ({"name": "", "email": "a@b.co", "password": PASSWORD}, "name"),
            ({"name": "<script>", "email": "a@b.co", "password": PASSWORD}, "name"),
            ({"name": "Ada", "email": "", "password": PASSWORD}, "email"),
            ({"name": "Ada", "email": "not-an-email", "password": PASSWORD}, "email"),
            ({"name": "Ada", "email": "a@@b.co", "password": PASSWORD}, "email"),
            ({"name": "Ada", "email": "a@b.co", "password": ""}, "password"),
            ({"name": "Ada", "email": "a@b.co", "password": "short1"}, "password"),
            ({"name": "Ada", "email": "a@b.co", "password": "onlyletters"}, "password"),
            ({"name": "Ada", "email": "a@b.co", "password": "password123"}, "password"),
            ({"name": "Ada", "email": "a@b.co", "password": "x" * 129 + "1"}, "password"),
        ]
        for body, field in cases:
            res = self.client.post("/auth/signup", json=body)
            self.assertEqual(res.status_code, 422, body)
            self.assertEqual(res.json()["detail"]["field"], field, body)
        self.assertEqual(self.client.post("/auth/signup", content="not json").status_code, 422)
        self.assertEqual(count(User), 0)

    def test_login_reads_the_stored_account(self):
        self.signup()
        client = self.new_client()
        res = client.post("/auth/login", json={"email": "ADA@example.com", "password": PASSWORD})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.session(client)["account"]["name"], "Ada Lovelace")

    def test_bad_logins_are_refused(self):
        self.signup()
        client = self.new_client()
        for body, status in (({"email": "ada@example.com", "password": "wrong pass 1"}, 401),
                             ({"email": "nobody@example.com", "password": PASSWORD}, 401),
                             ({"email": "ada@example.com", "password": ""}, 422),
                             ({"email": "", "password": PASSWORD}, 422)):
            self.assertEqual(client.post("/auth/login", json=body).status_code, status, body)
        self.assertIsNone(self.session(client)["account"])

    def test_logout_ends_the_session_but_keeps_the_account(self):
        self.signup()
        self.assertEqual(self.client.post("/auth/logout").status_code, 204)
        self.assertIsNone(self.session()["account"])
        self.assertEqual(count(User), 1)

    def test_deleted_account_signs_the_session_out(self):
        self.signup()
        with SessionLocal() as db:
            db.delete(db.scalar(select(User)))
            db.commit()
        self.assertIsNone(self.session()["account"])
        self.assertEqual(self.client.post("/api/library/apply", json={}).status_code, 401)


class ConnectTests(CrudTestCase):
    def test_connect_stores_the_project(self):
        uid = self.linked_user()
        res = self.client.post("/api/connect", json={"repo": "ada/shop", "project_key": "QA"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["delivered"])
        project = row(Project, user_id=uid)
        self.assertEqual((project.repo, project.jira_key, project.jira_name, project.hook_id),
                         ("ada/shop", "QA", "QA Board", 111))
        self.assertIsNotNone(project.webhook_verified_at)
        self.assertEqual(self.session()["project"],
                         {"repo": "ada/shop", "jira_key": "QA", "jira_name": "QA Board", "webhook_verified": True})
        self.assertEqual(self.session()["github"]["login"], "ada")
        self.assertEqual(self.session()["atlassian"]["site"], "ada.atlassian.net")

    def test_tokens_are_stored_encrypted(self):
        uid = self.linked_user()
        user = row(User, id=uid)
        self.assertNotEqual(user.github_token, "gh-token")
        self.assertEqual(unseal(user.github_token), "gh-token")

    def test_reconnect_updates_the_same_row(self):
        uid = self.connected_user()
        self.fakes["ensure_webhook"].return_value = 222
        res = self.client.post("/api/connect", json={"repo": "ada/blog", "project_key": "WEB"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(count(Project), 1)
        project = row(Project, user_id=uid)
        self.assertEqual((project.repo, project.jira_key, project.hook_id), ("ada/blog", "WEB", 222))
        self.fakes["delete_webhook"].assert_called_once_with("gh-token", "ada/shop", 111)

    def test_connect_refusals_store_nothing(self):
        self.assertEqual(self.client.post("/api/connect", json={"repo": "a/b", "project_key": "QA"}).status_code, 401)
        self.signup()
        self.assertEqual(self.client.post("/api/connect", json={"repo": "a/b", "project_key": "QA"}).status_code, 403)
        self.client.post("/auth/logout")
        self.client = self.new_client()
        self.linked_user("bob@example.com")
        for body, status in (({"repo": "no-slash", "project_key": "QA"}, 422),
                             ({"repo": "a/b/c", "project_key": "QA"}, 422),
                             ({"repo": "a b/c", "project_key": "QA"}, 422),
                             ({"repo": "a/b", "project_key": ""}, 422),
                             ({"repo": "a/b"}, 422),
                             ({"repo": "a/b", "project_key": "NOPE"}, 400)):
            self.assertEqual(self.client.post("/api/connect", json=body).status_code, status, body)
        self.assertEqual(count(Project), 0)
        self.fakes["ensure_webhook"].assert_not_called()

    def test_undelivered_ping_still_stores_the_project(self):
        self.fakes["ping_webhook"].side_effect = None
        uid = self.linked_user()
        with mock.patch("backend.api.time.sleep"):
            res = self.client.post("/api/connect", json={"repo": "ada/shop", "project_key": "QA"})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["delivered"])
        self.assertIsNotNone(res.json()["warning"])
        self.assertIsNone(row(Project, user_id=uid).webhook_verified_at)

    def test_signed_webhook_marks_the_project_verified(self):
        self.fakes["ping_webhook"].side_effect = None
        with mock.patch("backend.api.time.sleep"):
            uid = self.connected_user()
        body = json.dumps({"repository": {"full_name": "ada/shop"}}).encode()
        sig = "sha256=" + hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        for header in (None, "sha256=bad", sig[:-1] + "0"):
            headers = {"x-hub-signature-256": header} if header else {}
            self.assertEqual(self.client.post("/webhooks/github", content=body, headers=headers).status_code, 401)
            self.assertIsNone(row(Project, user_id=uid).webhook_verified_at)
        res = self.client.post("/webhooks/github", content=body, headers={"x-hub-signature-256": sig, "x-github-event": "ping"})
        self.assertEqual(res.status_code, 202)
        self.assertIsNotNone(row(Project, user_id=uid).webhook_verified_at)

    def test_webhook_with_bad_json(self):
        body = b"not json"
        sig = "sha256=" + hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertEqual(self.client.post("/webhooks/github", content=body, headers={"x-hub-signature-256": sig}).status_code, 400)


class LibraryTests(CrudTestCase):
    def test_upload_stores_specs_and_collection(self):
        uid = self.connected_user()
        res = self.apply(specs=[{"name": "a.spec.ts", "text": spec("a")}, {"name": "b.spec.ts", "text": spec("b")}],
                         collection={"name": "api.json", "text": collection("one", "two")})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {"saved_specs": 2, "removed_specs": 0, "saved_collection": True, "removed_collection": False})
        project_id = row(Project, user_id=uid).id
        a = row(SpecFile, project_id=project_id, name="a.spec.ts")
        self.assertEqual((a.content, a.size, a.test_count, a.revision), (spec("a"), len(spec("a").encode()), 1, 1))
        c = row(Collection, project_id=project_id)
        self.assertEqual((c.name, c.request_count, c.revision), ("api.json", 2, 1))
        session = self.session()
        self.assertEqual([s["name"] for s in session["specs"]], ["a.spec.ts", "b.spec.ts"])
        self.assertEqual(session["collection"]["text"], collection("one", "two"))

    def test_update_bumps_the_revision(self):
        self.connected_user()
        self.apply(specs=[{"name": "a.spec.ts", "text": spec("a")}], collection={"name": "api.json", "text": collection()})
        res = self.apply(specs=[{"name": "a.spec.ts", "text": spec("new"), "revision": 1}],
                         collection={"name": "api2.json", "text": collection("x", "y", "z"), "revision": 1})
        self.assertEqual(res.status_code, 200, res.text)
        a = row(SpecFile, name="a.spec.ts")
        self.assertEqual((a.content, a.revision), (spec("new"), 2))
        c = row(Collection)
        self.assertEqual((c.name, c.request_count, c.revision), ("api2.json", 3, 2))
        self.assertEqual((count(SpecFile), count(Collection)), (1, 1))

    def test_saving_the_same_content_writes_nothing(self):
        self.connected_user()
        self.apply(specs=[{"name": "a.spec.ts", "text": spec()}])
        res = self.apply(specs=[{"name": "a.spec.ts", "text": spec(), "revision": 1}])
        self.assertEqual(res.json()["saved_specs"], 0)
        self.assertEqual(row(SpecFile, name="a.spec.ts").revision, 1)

    def test_stale_or_missing_revisions_are_refused(self):
        self.connected_user()
        self.apply(specs=[{"name": "a.spec.ts", "text": spec("a")}], collection={"name": "api.json", "text": collection()})
        cases = [
            ({"specs": [{"name": "a.spec.ts", "text": spec("x")}]}, "exists"),
            ({"specs": [{"name": "a.spec.ts", "text": spec("x"), "revision": 5}]}, "changed"),
            ({"specs": [{"name": "gone.spec.ts", "text": spec("x"), "revision": 1}]}, "deleted"),
            ({"collection": {"name": "api.json", "text": collection("x")}}, "exists"),
            ({"delete_specs": [{"name": "a.spec.ts", "revision": 9}]}, "changed"),
            ({"delete_collection": {"revision": 9}}, "changed"),
        ]
        for body, reason in cases:
            res = self.apply(**body)
            self.assertEqual(res.status_code, 409, body)
            self.assertEqual(res.json()["detail"]["conflicts"][0]["reason"], reason, body)
        self.assertEqual((row(SpecFile, name="a.spec.ts").content, row(SpecFile, name="a.spec.ts").revision), (spec("a"), 1))
        self.assertEqual((count(SpecFile), row(Collection).revision), (1, 1))

    def test_invalid_uploads_store_nothing(self):
        self.connected_user()
        bad_specs = [
            {"name": "a.spec.ts", "text": ""},
            {"name": "a.spec.ts", "text": "test('x', () => {})"},
            {"name": "a.spec.ts", "text": "import { test } from '@playwright/test';\nconst x = 1;"},
            {"name": "a.spec.ts", "text": "import { test } from '@playwright/test';\ntest('x', () => {"},
            {"name": "a.spec.ts", "text": "import { test } from '@playwright/test';\nrequire('child_process');\ntest('x', () => {});"},
            {"name": "a.txt", "text": spec()},
            {"name": ".spec.ts", "text": spec()},
            {"name": "../a.spec.ts", "text": spec()},
            {"name": "a" * 256 + ".spec.ts", "text": spec()},
        ]
        for f in bad_specs:
            self.assertEqual(self.apply(specs=[f]).status_code, 422, f["name"][:40] + " " + f["text"][:60])
        bad_collections = [
            {"name": "api.json", "text": "not json"},
            {"name": "api.json", "text": json.dumps({"info": {"name": "API"}, "item": []})},
            {"name": "api.json", "text": json.dumps({"info": {"name": "API", "schema": SCHEMA}, "item": []})},
            {"name": "api.txt", "text": collection()},
            {"name": "api.json", "text": ""},
        ]
        for c in bad_collections:
            self.assertEqual(self.apply(collection=c).status_code, 422, c)
        self.assertEqual((count(SpecFile), count(Collection)), (0, 0))

    def test_one_bad_file_stores_nothing(self):
        self.connected_user()
        res = self.apply(specs=[{"name": "good.spec.ts", "text": spec()}, {"name": "bad.spec.ts", "text": "oops"}],
                         collection={"name": "api.json", "text": collection()})
        self.assertEqual(res.status_code, 422)
        self.assertIn("bad.spec.ts", res.json()["detail"]["files"])
        self.assertEqual((count(SpecFile), count(Collection)), (0, 0))

    def test_conflicting_requests_store_nothing(self):
        self.connected_user()
        self.apply(specs=[{"name": "a.spec.ts", "text": spec()}])
        cases = [
            {"specs": [{"name": "b.spec.ts", "text": spec()}, {"name": "b.spec.ts", "text": spec()}]},
            {"specs": [{"name": "c.spec.ts", "text": spec()}, {"name": "C.spec.ts", "text": spec()}]},
            {"specs": [{"name": "A.spec.ts", "text": spec()}]},
            {"specs": [{"name": "a.spec.ts", "text": spec("x"), "revision": 1}], "delete_specs": [{"name": "a.spec.ts"}]},
            {"delete_specs": [{"name": "a.spec.ts"}, {"name": "a.spec.ts"}]},
            {"collection": {"name": "api.json", "text": collection()}, "delete_collection": {}},
            {"specs": [{"name": "a.spec.ts", "text": spec(), "revision": 0}]},
        ]
        for body in cases:
            self.assertEqual(self.apply(**body).status_code, 422, body)
        self.assertEqual([s["name"] for s in self.session()["specs"]], ["a.spec.ts"])

    def test_at_most_fifty_specs(self):
        self.connected_user()
        res = self.apply(specs=[{"name": f"t{i}.spec.ts", "text": spec(f"case {i}")} for i in range(50)])
        self.assertEqual(res.status_code, 200, res.text)
        res = self.apply(specs=[{"name": "extra.spec.ts", "text": spec()}])
        self.assertEqual(res.status_code, 422)
        self.assertEqual(count(SpecFile), 50)

    def test_delete_removes_the_rows(self):
        self.connected_user()
        self.apply(specs=[{"name": "a.spec.ts", "text": spec()}, {"name": "b.spec.ts", "text": spec()}],
                   collection={"name": "api.json", "text": collection()})
        self.assertEqual(self.client.delete("/api/library/specs/a.spec.ts?revision=1").status_code, 204)
        self.assertIsNone(row(SpecFile, name="a.spec.ts"))
        self.assertIsNotNone(row(SpecFile, name="b.spec.ts"))
        self.assertEqual(self.client.delete("/api/library/specs/a.spec.ts").status_code, 204)  # already gone is fine
        self.assertEqual(self.client.delete("/api/library/collection?revision=1").status_code, 204)
        self.assertEqual(count(Collection), 0)
        self.assertEqual(self.client.delete("/api/library/collection").status_code, 204)
        self.assertEqual([s["name"] for s in self.session()["specs"]], ["b.spec.ts"])
        self.assertIsNone(self.session()["collection"])

    def test_save_and_delete_in_one_request(self):
        self.connected_user()
        self.apply(specs=[{"name": "old.spec.ts", "text": spec()}])
        res = self.apply(specs=[{"name": "new.spec.ts", "text": spec()}], delete_specs=[{"name": "old.spec.ts", "revision": 1}])
        self.assertEqual(res.json(), {"saved_specs": 1, "removed_specs": 1, "saved_collection": False, "removed_collection": False})
        self.assertEqual([s["name"] for s in self.session()["specs"]], ["new.spec.ts"])

    def test_bad_delete_requests(self):
        self.connected_user()
        self.apply(specs=[{"name": "a.spec.ts", "text": spec()}])
        self.assertEqual(self.client.delete("/api/library/specs/a.spec.ts?revision=0").status_code, 422)
        self.assertEqual(self.client.delete("/api/library/specs/a.spec.ts?revision=abc").status_code, 422)
        self.assertEqual(self.client.delete("/api/library/collection?revision=0").status_code, 422)
        self.assertEqual(self.client.delete("/api/library/specs/" + "a" * 256).status_code, 422)
        self.assertEqual(self.client.delete("/api/library/specs/a.spec.ts?revision=2").status_code, 409)
        self.assertEqual(count(SpecFile), 1)

    def test_library_needs_a_session_and_a_project(self):
        body = {"specs": [{"name": "a.spec.ts", "text": spec()}]}
        self.assertEqual(self.apply(**body).status_code, 401)
        self.assertEqual(self.client.delete("/api/library/specs/a.spec.ts").status_code, 401)
        self.assertEqual(self.client.delete("/api/library/collection").status_code, 401)
        self.linked_user()
        self.assertEqual(self.apply(**body).status_code, 409)
        self.assertEqual(self.client.delete("/api/library/collection").status_code, 409)
        self.assertEqual(count(SpecFile), 0)

    def test_users_only_see_and_change_their_own_library(self):
        self.connected_user()
        self.apply(specs=[{"name": "a.spec.ts", "text": spec("ada")}])
        bob = self.new_client()
        self.connected_user("bob@example.com", "bob/app", client=bob)
        self.assertEqual(self.session(bob)["specs"], [])
        self.assertEqual(bob.delete("/api/library/specs/a.spec.ts").status_code, 204)  # nothing of Bob's to delete
        self.assertEqual(self.apply(client=bob, specs=[{"name": "a.spec.ts", "text": spec("bob")}]).status_code, 200)
        self.assertEqual(count(SpecFile), 2)
        self.assertEqual(self.session()["specs"][0]["text"], spec("ada"))
        self.assertEqual(self.session(bob)["specs"][0]["text"], spec("bob"))


class DisconnectTests(CrudTestCase):
    def fill_library(self, client=None):
        res = self.apply(client=client, specs=[{"name": "a.spec.ts", "text": spec()}],
                         collection={"name": "api.json", "text": collection()})
        self.assertEqual(res.status_code, 200, res.text)

    def test_disconnect_removes_the_project_and_library(self):
        self.connected_user()
        self.fill_library()
        self.assertEqual(self.client.post("/api/disconnect").status_code, 204)
        self.assertEqual((count(Project), count(SpecFile), count(Collection)), (0, 0, 0))
        self.fakes["delete_webhook"].assert_called_once_with("gh-token", "ada/shop", 111)
        session = self.session()
        self.assertIsNone(session["project"])
        self.assertEqual(session["specs"], [])
        self.assertIsNotNone(session["github"])  # GitHub and Jira stay linked
        res = self.client.post("/api/connect", json={"repo": "ada/blog", "project_key": "QA"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.session()["specs"], [])

    def test_disconnect_twice_or_without_a_project(self):
        self.assertEqual(self.client.post("/api/disconnect").status_code, 401)
        self.linked_user()
        self.assertEqual(self.client.post("/api/disconnect").status_code, 204)
        self.fakes["delete_webhook"].assert_not_called()

    def test_github_being_down_does_not_block_disconnect(self):
        self.connected_user()
        self.fakes["delete_webhook"].side_effect = HTTPException(502, "Could not reach api.github.com")
        self.assertEqual(self.client.post("/api/disconnect").status_code, 204)
        self.assertEqual(count(Project), 0)

    def test_disconnect_leaves_other_users_alone(self):
        self.connected_user()
        bob = self.new_client()
        self.connected_user("bob@example.com", "bob/app", client=bob)
        self.fill_library(client=bob)
        self.assertEqual(self.client.post("/api/disconnect").status_code, 204)
        self.assertEqual(self.session(bob)["project"]["repo"], "bob/app")
        self.assertEqual((count(Project), count(SpecFile), count(Collection)), (1, 1, 1))

    def test_library_after_disconnect_needs_a_new_connect(self):
        self.connected_user()
        self.client.post("/api/disconnect")
        self.assertEqual(self.apply(specs=[{"name": "a.spec.ts", "text": spec()}]).status_code, 409)


class AccountSettingsTests(CrudTestCase):
    def test_rename_stores_the_name(self):
        self.signup()
        res = self.client.post("/api/account/name", json={"name": "  Ada   King "})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["account"]["name"], "Ada King")
        self.assertEqual(row(User, email="ada@example.com").name, "Ada King")

    def test_bad_names_change_nothing(self):
        self.assertEqual(self.client.post("/api/account/name", json={"name": "Ada"}).status_code, 401)
        self.signup()
        for name in ("", "   ", "<b>", "a" * 81, "nul\x00here"):
            res = self.client.post("/api/account/name", json={"name": name})
            self.assertEqual(res.status_code, 422, name)
            self.assertEqual(res.json()["detail"]["field"], "name")
        self.assertEqual(row(User).name, "Ada Lovelace")

    def test_password_change(self):
        self.signup()
        other = self.new_client()
        other.post("/auth/login", json={"email": "ada@example.com", "password": PASSWORD})
        res = self.client.post("/api/account/password", json={"password": PASSWORD, "new_password": "new secret 42"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIsNotNone(self.session()["account"])  # this session stays signed in
        self.assertIsNone(self.session(other)["account"])  # every other session is signed out
        fresh = self.new_client()
        self.assertEqual(fresh.post("/auth/login", json={"email": "ada@example.com", "password": PASSWORD}).status_code, 401)
        self.assertEqual(fresh.post("/auth/login", json={"email": "ada@example.com", "password": "new secret 42"}).status_code, 200)

    def test_bad_password_changes_store_nothing(self):
        self.signup()
        before = row(User).password_hash
        cases = [
            ({"password": "wrong pass 1", "new_password": "new secret 42"}, 400, "password"),
            ({"password": "", "new_password": "new secret 42"}, 400, "password"),
            ({"password": PASSWORD, "new_password": ""}, 422, "new_password"),
            ({"password": PASSWORD, "new_password": "short1"}, 422, "new_password"),
            ({"password": PASSWORD, "new_password": "password123"}, 422, "new_password"),
            ({"password": PASSWORD, "new_password": "Ada Lovelace 1"}, 422, "new_password"),
            ({"password": PASSWORD, "new_password": PASSWORD}, 422, "new_password"),
        ]
        for body, status, field in cases:
            res = self.client.post("/api/account/password", json=body)
            self.assertEqual(res.status_code, status, body)
            self.assertEqual(res.json()["detail"]["field"], field, body)
        self.assertEqual(row(User).password_hash, before)
        self.assertIsNotNone(self.session()["account"])

    def test_wrong_passwords_are_throttled(self):
        self.signup()
        for _ in range(5):
            self.client.post("/api/account/password", json={"password": "wrong pass 1", "new_password": "new secret 42"})
        res = self.client.post("/api/account/password", json={"password": PASSWORD, "new_password": "new secret 42"})
        self.assertEqual(res.status_code, 429)

    def test_github_accounts_have_no_password_to_change(self):
        self.signup()
        with SessionLocal() as db:
            db.scalar(select(User)).password_hash = None
            db.commit()
        res = self.client.post("/api/account/password", json={"password": "", "new_password": "new secret 42"})
        self.assertEqual(res.status_code, 409)
        self.assertIsNone(row(User).password_hash)

    def test_delete_removes_everything(self):
        uid = self.connected_user()
        self.apply(specs=[{"name": "a.spec.ts", "text": spec()}], collection={"name": "api.json", "text": collection()})
        with SessionLocal() as db:
            db.add(RecoveryCode(user_id=uid, code_hash=hash_password("abcdefghjk")))
            db.commit()
        other = self.new_client()
        other.post("/auth/login", json={"email": "ada@example.com", "password": PASSWORD})
        self.assertEqual(self.client.post("/api/account/delete", json={"password": PASSWORD}).status_code, 204)
        self.assertEqual((count(User), count(Project), count(SpecFile), count(Collection), count(RecoveryCode)), (0, 0, 0, 0, 0))
        self.fakes["delete_webhook"].assert_called_once()
        self.assertIsNone(self.session()["account"])
        self.assertIsNone(self.session(other)["account"])
        self.assertEqual(other.post("/api/library/apply", json={}).status_code, 401)
        fresh = self.new_client()
        self.assertEqual(fresh.post("/auth/login", json={"email": "ada@example.com", "password": PASSWORD}).status_code, 401)
        self.assertEqual(self.signup(client=fresh).status_code, 201)  # the email is free again

    def test_bad_deletes_keep_the_account(self):
        self.assertEqual(self.client.post("/api/account/delete", json={"password": PASSWORD}).status_code, 401)
        self.connected_user()
        for body in ({"password": "wrong pass 1"}, {"password": ""}, {}):
            res = self.client.post("/api/account/delete", json=body)
            self.assertEqual(res.status_code, 400, body)
        self.assertEqual((count(User), count(Project)), (1, 1))
        self.assertIsNotNone(self.session()["account"])

    def test_delete_with_two_step_needs_a_code(self):
        self.signup()
        secret = pyotp.random_base32()
        with SessionLocal() as db:
            db.scalar(select(User)).totp_secret = seal_totp(secret)
            db.commit()
        for body in ({"password": PASSWORD}, {"password": PASSWORD, "code": "000000"}):
            res = self.client.post("/api/account/delete", json=body)
            self.assertEqual(res.status_code, 400, body)
            self.assertEqual(res.json()["detail"]["field"], "code")
        self.assertEqual(count(User), 1)
        res = self.client.post("/api/account/delete", json={"password": PASSWORD, "code": pyotp.TOTP(secret).now()})
        self.assertEqual(res.status_code, 204, res.text)
        self.assertEqual(count(User), 0)

    def test_github_account_delete_needs_a_recent_sign_in(self):
        self.signup()
        with SessionLocal() as db:
            db.scalar(select(User)).password_hash = None
            db.commit()
        with mock.patch("backend.twofactor.RECENT_SIGN_IN", -1):  # as if the sign in was long ago
            res = self.client.post("/api/account/delete", json={})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["detail"]["field"], "reauth")
        self.assertEqual(self.client.post("/api/account/delete", json={}).status_code, 204)
        self.assertEqual(count(User), 0)


if __name__ == "__main__":
    unittest.main()
