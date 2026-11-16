"""System test of the demo: the Shoplite staging app in staging/server.py, the sample tests in
samples/test-data/shoplite, real Playwright and real Newman, run by the real Test Agent code.
It proves what the mentors will see for each switch on /demo.

Run:  python -m unittest tests.test_staging_demo
"""
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from backend import execution as ex
from staging import server as shop

from .test_qa_flow import QaTestCase

SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "test-data" / "shoplite"
SPECS = ("shoplite-cart.spec.ts", "shop.spec.ts", "shoplite-wishlist.spec.ts")


@unittest.skipIf(ex.tools_ready(), "runner/ has no Playwright or Newman: run npm install in runner")
class StagingDemoTests(QaTestCase):
    def setUp(self):
        super().setUp()
        for switch in shop.SWITCHES:
            shop.SWITCHES[switch] = False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), shop.Shop)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        for name in ("pw", "nm", "probe", "tools"):  # the real tools and the real staging check
            self.patchers[name].stop()

    def run_demo(self, **switches) -> dict:
        """One Run Now on the sample library. Returns {test title: outcome}."""
        shop.SWITCHES.update(switches)
        aid = self.ready(modules=("cart",), label="High")
        url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.assertEqual(self.client.post("/api/project/staging", json={"url": url}).status_code, 200)
        res = self.apply(specs=[{"name": n, "text": (SAMPLES / n).read_text(encoding="utf-8")} for n in SPECS],
                         delete_specs=[{"name": "cart.spec.ts", "revision": 1}],
                         collection={"name": "shoplite.postman_collection.json", "revision": 1,
                                     "text": (SAMPLES / "shoplite.postman_collection.json").read_text(encoding="utf-8")})
        self.assertEqual(res.status_code, 200, res.text)
        detail = self.start(aid)
        self.assertIn(detail["run"]["status"], ("finished", "flagged"), detail["run"])
        return {r["title"].split(" › ")[-1]: r["outcome"] for r in detail["results"]}

    def test_a_healthy_shop_passes_and_the_missing_page_is_pending(self):
        got = self.run_demo()
        self.assertEqual(got.pop("wishlist page lists saved items"), "deployment_pending")
        self.assertEqual(len(got), 13, got)  # 4 + 2 UI tests and 7 API requests
        self.assertEqual(set(got.values()), {"passed"}, got)

    def test_the_cart_bug_is_a_real_bug_in_the_ui_tests(self):
        got = self.run_demo(cart_bug=True, wishlist_page=True)
        self.assertEqual(got["adding a product updates the cart total"], "real_bug")
        self.assertEqual(got["customer can log in, add a product and check out"], "real_bug")
        self.assertEqual(got["wishlist page lists saved items"], "passed")  # deployed now, so it runs
        self.assertEqual(got["Login"], "passed")

    def test_the_orders_bug_is_a_real_bug_in_the_api_and_the_ui(self):
        got = self.run_demo(orders_bug=True)
        self.assertEqual(got["Checkout"], "real_bug")
        self.assertEqual(got["checkout places the order"], "real_bug")
        self.assertEqual(got["adding a product updates the cart total"], "passed")
