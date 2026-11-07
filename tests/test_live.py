"""Live run status over the WebSocket at /api/live (SRS 3.4). Needs the built frontend (npm run build)."""
import unittest

from starlette.websockets import WebSocketDisconnect

from agents.trace import add_listener, trace
from backend import live
from backend.live import describe, hub

from .test_agents_real import AgentCase, reply
from .test_analysis_integration import AnalysisTestCase, REPO, payload

ORIGIN = {"origin": "http://testserver"}


def texts(lines):
    return [m["text"] for m in (describe(line) for line in lines) if m]


class MessageTests(unittest.TestCase):
    def line(self, event, **fields):
        return {"at": "2026-11-07T10:00:00.000+00:00", "run_id": "r1", "pr_id": "ada/shop#7", "event": event, **fields}

    def test_each_step_gets_a_short_message(self):
        cases = {
            ("service.delivery", (("action", "opened"),)): "New pull request received from GitHub",
            ("run.start", ()): "Manager agent started",
            ("github.pr_read", (("files", 3),)): "reading the changes (3 files)",
            ("rules.scored", (("risk_label", "High"), ("score", 7))): "scored it High (7 points)",
            ("analysis.model_called", (("model", "groq/x"),)): "asking the AI model (groq/x)",
            ("manager.validated", (("accepted", True), ("attempt", 1))): "Manager agent verified the output",
            ("manager.validated", (("accepted", False), ("attempt", 1))): "rejected the output (attempt 1 of 3)",
            ("manager.retry", (("next_attempt", 2), ("of", 3))): "Analysis agent is doing the work again (attempt 2 of 3)",
            ("manager.decided", (("status", "approved"), ("risk_label", "Low"))): "approved the result: Low risk",
            ("manager.decided", (("status", "needs_human_review"),)): "needs a human review",
        }
        for (event, fields), expected in cases.items():
            message = describe(self.line(event, **dict(fields)))
            self.assertIn(expected, message["text"], event)
            self.assertEqual((message["repo"], message["pr"]), ("ada/shop", 7))

    def test_the_last_message_of_a_run_is_marked_done(self):
        for event, fields in (("service.saved", {"state": "scored"}), ("service.failed", {}), ("run.crashed", {}),
                              ("run.timed_out", {}), ("service.skipped", {})):
            self.assertTrue(describe(self.line(event, **fields))["done"], event)
        self.assertFalse(describe(self.line("rules.scored", risk_label="Low", score=2))["done"])

    def test_internal_steps_and_lines_without_a_pull_request_are_not_sent(self):
        self.assertIsNone(describe(self.line("analysis.prompt_built")))
        self.assertIsNone(describe(self.line("run.end")))
        self.assertIsNone(describe({**self.line("run.start"), "pr_id": None}))


class ManagerRetryIsAnnounced(AgentCase):
    def test_a_rejected_answer_shows_the_analysis_agent_working_again(self):
        lines = []
        add_listener(lines.append)
        self.addCleanup(lambda: __import__("agents.trace", fromlist=["_listeners"])._listeners.remove(lines.append))
        self.script(reply("short", []), reply())
        result = self.run_agent()
        self.assertEqual((result["status"], result["attempts"]), ("approved", 2))
        shown = texts(lines)
        rejected = next(i for i, t in enumerate(shown) if "rejected the output (attempt 1 of 3)" in t)
        self.assertIn("Analysis agent is doing the work again (attempt 2 of 3)", shown[rejected + 1])
        self.assertIn("Manager agent verified the output", shown[-2])
        self.assertIn("Manager agent approved the result: High risk", shown[-1])

    def test_no_retry_message_after_the_last_attempt(self):
        lines = []
        add_listener(lines.append)
        self.addCleanup(lambda: __import__("agents.trace", fromlist=["_listeners"])._listeners.remove(lines.append))
        self.script(reply("short", []))
        self.run_agent()
        shown = texts(lines)
        self.assertEqual(sum("doing the work again" in t for t in shown), 2)  # before attempts 2 and 3 only
        self.assertIn("needs a human review", shown[-1])


class SocketTests(AnalysisTestCase):
    def setUp(self):
        super().setUp()
        hub.recent.clear()

    def test_signed_out_pages_are_refused(self):
        with self.client.websocket_connect("/api/live", headers=ORIGIN) as ws:
            with self.assertRaises(WebSocketDisconnect) as refused:
                ws.receive_json()
        self.assertEqual(refused.exception.code, 4401)

    def test_other_sites_are_refused(self):
        self.connected_user()
        for headers in ({"origin": "https://evil.example"}, {}):
            with self.assertRaises(WebSocketDisconnect) as refused:
                with self.client.websocket_connect("/api/live", headers=headers):
                    pass
            self.assertEqual(refused.exception.code, 1008)

    def test_steps_of_the_connected_repository_arrive_in_order(self):
        self.connected_user()
        with self.client.websocket_connect("/api/live", headers=ORIGIN) as ws:
            trace("run.start", "someone/else#1")  # another repository: never sent
            trace("run.start", f"{REPO}#5")
            trace("rules.scored", f"{REPO}#5", risk_label="Medium", score=4)
            first, second = ws.receive_json(), ws.receive_json()
        self.assertEqual((first["pr"], first["event"]), (5, "run.start"))
        self.assertEqual(second["text"], "Risk rules scored it Medium (4 points)")
        self.assertEqual(first["repo"], REPO)

    def test_a_page_opened_during_a_run_gets_the_earlier_steps(self):
        self.connected_user()
        trace("run.start", f"{REPO}#6")
        with self.client.websocket_connect("/api/live", headers=ORIGIN) as ws:
            message = ws.receive_json()
        self.assertEqual((message["pr"], message["event"], message["replay"]), (6, "run.start", True))

    def test_a_webhook_delivery_streams_the_whole_run(self):
        self.connected_user()
        with self.fake_manager(), self.client.websocket_connect("/api/live", headers=ORIGIN) as ws:
            self.assertEqual(self.deliver(payload()).status_code, 202)
            events = []
            while not events or not events[-1]["done"]:
                events.append(ws.receive_json())
        names = [e["event"] for e in events]
        self.assertEqual(names[0], "service.delivery")
        self.assertEqual(names[-1], "service.saved")
        self.assertEqual(events[-1]["text"], "Result saved")
        self.assertTrue(all(e["pr"] == events[0]["pr"] for e in events))

    def test_signing_out_elsewhere_closes_new_connections(self):
        self.connected_user()
        other = self.new_client()
        other.cookies.update(self.client.cookies)
        self.client.post("/auth/logout")
        with other.websocket_connect("/api/live", headers=ORIGIN) as ws:
            with self.assertRaises(WebSocketDisconnect) as refused:
                ws.receive_json()
        self.assertEqual(refused.exception.code, 4401)

    def test_csp_allows_the_socket(self):
        csp = self.client.get("/login").headers["content-security-policy"]
        self.assertIn("connect-src 'self' ws", csp)


if __name__ == "__main__":
    unittest.main()
