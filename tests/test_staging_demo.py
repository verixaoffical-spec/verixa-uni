"""System test of the demo: the TaskFlow staging site in staging/server.py, the sample tests in
samples/test-data/demo-site, real Playwright and real Newman, run by the real Test Agent code.
It proves what the mentors will see for each switch on /demo.

Run:  python -m unittest tests.test_staging_demo
"""
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from backend import execution as ex
from staging import server as site

from .test_qa_flow import QaTestCase

SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "test-data" / "demo-site"
SPECS = ("taskflow.spec.ts", "taskflow-docs.spec.ts")
COLLECTION = "taskflow.postman_collection.json"
PENDING = "the documentation page explains how to add a task"


@unittest.skipIf(ex.tools_ready(), "runner/ has no Playwright or Newman: run npm install in runner")
class StagingDemoTests(QaTestCase):
    def setUp(self):
        super().setUp()
        for switch in site.SWITCHES:
            site.SWITCHES[switch] = False
        site.TASKS.clear()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), site.Site)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        for name in ("pw", "nm", "probe", "tools"):  # the real tools and the real staging check
            self.patchers[name].stop()

    def run_demo(self, **switches) -> dict:
        """One Run Now on the sample library. Returns {test title: outcome}."""
        site.SWITCHES.update(switches)
        aid = self.ready(modules=("pricing",), label="High")
        url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.assertEqual(self.client.post("/api/project/staging", json={"url": url}).status_code, 200)
        res = self.apply(specs=[{"name": n, "text": (SAMPLES / n).read_text(encoding="utf-8")} for n in SPECS],
                         delete_specs=[{"name": "cart.spec.ts", "revision": 1}],
                         collection={"name": COLLECTION, "revision": 1, "text": (SAMPLES / COLLECTION).read_text(encoding="utf-8")})
        self.assertEqual(res.status_code, 200, res.text)
        detail = self.start(aid)
        self.assertIn(detail["run"]["status"], ("finished", "flagged"), detail["run"])
        return {r["title"].split(" › ")[-1]: r["outcome"] for r in detail["results"]}

    def bugs(self, got: dict) -> set:
        return {title for title, outcome in got.items() if outcome == "real_bug"}

    def test_a_healthy_site_passes_and_the_missing_page_is_pending(self):
        got = self.run_demo()
        self.assertEqual(got.pop(PENDING), "deployment_pending")
        self.assertEqual(len(got), 14, got)  # 5 screen tests and 9 API requests
        self.assertEqual(set(got.values()), {"passed"}, got)

    def test_the_pricing_bug_is_found_by_the_screen_test_and_the_api_test(self):
        got = self.run_demo(pricing_bug=True)
        self.assertEqual(self.bugs(got), {"the pricing page shows the monthly prices and the discounted yearly prices", "List plans"})

    def test_the_contact_bug_is_found_by_the_screen_test_and_the_api_test(self):
        got = self.run_demo(contact_bug=True)
        self.assertEqual(self.bugs(got), {"the contact form asks for every field, then sends the message", "Contact message is accepted"})

    def test_the_tasks_bug_is_found_by_the_screen_test_and_the_api_test(self):
        got = self.run_demo(tasks_bug=True)
        self.assertEqual(self.bugs(got), {"a signed in user can add a task and sees it in the list", "The task is in the list"})

    def test_once_the_docs_page_is_deployed_its_test_runs_and_passes(self):
        got = self.run_demo(docs_page=True)
        self.assertEqual(got[PENDING], "passed")
        self.assertEqual(self.bugs(got), set())
