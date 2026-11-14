"""System test for UC4 and UC6: real Playwright and real Newman, run by the real Test Agent code, against a small
staging app started here. Only the model and GitHub are faked. Needs `npm install` in runner/ and a Playwright browser.

The staging app has one bug on purpose (the cart total is wrong, /api/orders crashes), one page that is not deployed
(/wishlist answers 404) and one endpoint that is not deployed (/api/coupons answers 404).

Run:  .\\.venv\\Scripts\\python.exe -m unittest tests.test_qa_system
"""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from backend import execution as ex

from .test_qa_flow import QaTestCase

PAGE = b"""<!doctype html><html><head><title>Shoplite</title></head><body>
<h1>Shoplite</h1><p id="total">Total: 30</p>
<script>console.log('cart loaded'); fetch('/api/health');</script></body></html>"""


class Staging(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, kind="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        routes = {"/": (200, PAGE, "text/html"), "/api/health": (200, b'{"ok":true}', "application/json"),
                  "/api/orders": (500, b'{"error":"database password=hunter2secret is wrong"}', "application/json")}
        code, body, kind = routes.get(self.path, (404, b"not found", "text/plain"))
        self.send(code, body, kind)


SPECS = {
    "home.spec.ts": """import { test, expect } from '@playwright/test';
test('home shows the shop name', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('h1')).toHaveText('Shoplite');
});
test('cart total is right', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#total')).toHaveText('Total: 20', { timeout: 1500 });
});
test.skip('skipped on purpose', async ({ page }) => { await page.goto('/'); });
""",
    "wishlist.spec.ts": """import { test, expect } from '@playwright/test';
test('wishlist lists saved items', async ({ page }) => {
  await page.goto('/wishlist');
  await expect(page.locator('h1')).toHaveText('Wishlist');
});
""",
}


def collection(base_requests):
    items = [{"name": name, "request": {"method": "GET", "url": "{{baseUrl}}" + path},
              "event": [{"listen": "test", "script": {"exec": ["pm.test('status 200', () => pm.response.to.have.status(200));"]}}]}
             for name, path in base_requests]
    return json.dumps({"info": {"name": "Shop API", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
                       "item": items})


@unittest.skipIf(ex.tools_ready(), "runner/ has no Playwright or Newman: run npm install in runner")
class RealToolsTests(QaTestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Staging)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        for name in ("pw", "nm", "probe", "tools"):  # the real tools this time, and the real staging check
            self.patchers[name].stop()
        self.staging = f"http://127.0.0.1:{self.server.server_address[1]}"

    def test_a_real_run_sorts_every_result_and_keeps_the_proof(self):
        aid = self.ready(modules=("cart",), label="High")
        self.assertEqual(self.client.post("/api/project/staging", json={"url": self.staging}).status_code, 200)
        res = self.apply(specs=[{"name": n, "text": t} for n, t in SPECS.items()],
                         delete_specs=[{"name": "cart.spec.ts", "revision": 1}],
                         collection={"name": "shop.json", "revision": 1, "text": collection(
                             [("health", "/api/health"), ("orders", "/api/orders"), ("coupons", "/api/coupons")])})
        self.assertEqual(res.status_code, 200, res.text)
        detail = self.start(aid)
        run = detail["run"]
        # The fake model explains every failure as the cart total, so the Manager accepts that for the cart test and
        # rejects it for the orders test three times: that ticket is flagged, and so is the run.
        self.assertEqual(run["status"], "flagged", run)
        got = {r["title"].split(" › ")[-1]: r["outcome"] for r in detail["results"]}
        self.assertEqual(got, {"home shows the shop name": "passed", "cart total is right": "real_bug",
                               "skipped on purpose": "skipped", "wishlist lists saved items": "deployment_pending",
                               "health": "passed", "orders": "real_bug", "coupons": "deployment_pending"}, got)

        ui_bug = next(r for r in detail["results"] if r["title"].endswith("cart total is right"))
        self.assertTrue(ui_bug["retried"])  # a failure gets one more attempt
        kinds = {e["type"]: e["id"] for e in ui_bug["evidence"]}
        self.assertEqual(set(kinds), {"screenshot", "trace", "console_log", "network_log"})
        shot = self.client.get(f"/api/evidence/{kinds['screenshot']}")
        self.assertEqual((shot.status_code, shot.headers["content-type"], shot.content[:4]), (200, "image/png", b"\x89PNG"))
        trace = self.client.get(f"/api/evidence/{kinds['trace']}")
        self.assertIn("attachment", trace.headers["content-disposition"])
        self.assertIn("cart loaded", self.client.get(f"/api/evidence/{kinds['console_log']}").text)
        self.assertIn("/api/health", self.client.get(f"/api/evidence/{kinds['network_log']}").text)

        api_bug = next(r for r in detail["results"] if r["title"] == "orders")
        network = self.client.get(f"/api/evidence/{api_bug['evidence'][-1]['id']}").text
        self.assertIn("-> 500", network)
        self.assertNotIn("hunter2secret", network)  # secrets hidden in saved logs
        flagged = {t["test"]: t["flagged"] for t in detail["tickets"]}
        self.assertEqual(flagged, {"cart total is right": False, "orders": True})
        self.assertFalse(list((ex.RUNNER / "runs").glob(f"run_{run['id']}")))  # the run folder is gone

    def test_an_uploaded_test_cannot_read_the_servers_secrets(self):
        """Even code that slipped past the upload checks sees an environment without .env values."""
        aid = self.ready(label="High")
        self.client.post("/api/project/staging", json={"url": self.staging})
        sneaky = ("import { test, expect } from '@playwright/test';\n"
                  "test('environment is empty of secrets', async () => {\n"
                  "  const env = (globalThis as any)['proc' + 'ess'].env;\n"
                  "  expect(env.SECRET_KEY ?? 'none').toBe('none');\n"
                  "  expect(env.DATABASE_URL ?? 'none').toBe('none');\n"
                  "  expect(env.GITHUB_CLIENT_SECRET ?? 'none').toBe('none');\n});\n")
        from backend.db import Project, SessionLocal, SpecFile
        from sqlalchemy import select
        with SessionLocal() as db:  # stored directly: the upload checks would refuse this file
            pid = db.scalar(select(Project.id))
            for s in db.scalars(select(SpecFile)):
                db.delete(s)
            db.add(SpecFile(project_id=pid, name="sneaky.spec.ts", content=sneaky, size=len(sneaky), test_count=1))
            db.commit()
        self.apply(delete_collection={"revision": 1})
        detail = self.start(aid)
        self.assertEqual([r["outcome"] for r in detail["results"]], ["passed"], detail)
