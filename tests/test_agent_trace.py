"""The agents' trace log, read back after real Manager and Analysis Agent runs. Only GitHub and the model are faked."""
import asyncio
import json
import logging
import os
import unittest
from unittest import mock

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from agents import analysis
from agents.analysis import ANALYSES, _CACHE, analysis_agent
from agents.runner import run_manager
from agents.trace import _ConsoleLine, agent_run, mask, trace

TOKEN = "ghp_doNotLogThisToken"
PR = {"title": "Change the charge", "head": {"sha": "a" * 40}, "base": {"sha": "b" * 40, "repo": {"id": 7}},
      "html_url": "https://github.com/ada/shop/pull/4", "updated_at": "2026-11-06T00:00:00Z", "state": "open"}
FILES = [{"filename": "src/payments/session.ts", "additions": 3, "deletions": 1, "patch": "@@ -1 +1 @@\n+const charge = createCharge();\n"}]
GOOD = json.dumps({"reasoning": "The createCharge line in src/payments/session.ts changes how a payment is made.",
                   "suggested_test_areas": ["createCharge charges once", "a declined card makes no order"]})


class FakeModel(BaseLlm):
    model: str = "fake"
    replies: list = []

    async def generate_content_async(self, llm_request, stream=False):
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=reply)]))


def lines() -> list[dict]:
    with open(os.environ["AGENT_TRACE_FILE"], encoding="utf-8") as file:
        return [json.loads(line) for line in file]


class TraceTests(unittest.TestCase):
    def setUp(self):
        ANALYSES.clear()
        _CACHE.clear()
        self.addCleanup(ANALYSES.clear)
        self.addCleanup(_CACHE.clear)
        for patcher in (mock.patch.object(analysis, "fetch_pr", return_value=(PR, FILES)),
                        mock.patch.object(analysis, "count_fix_commits", return_value=0),
                        mock.patch.object(analysis, "count_defects", return_value=0),
                        mock.patch.object(analysis, "_has_key", return_value=True),
                        mock.patch.object(analysis_agent.writers[0], "model", FakeModel(replies=[GOOD]))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_and_read(self, replies=None, pr_id="ada/shop#4"):
        if replies:
            analysis_agent.writers[0].model = FakeModel(replies=replies)
        before = len(lines()) if os.path.exists(os.environ["AGENT_TRACE_FILE"]) else 0
        result = asyncio.run(run_manager(pr_id, TOKEN))
        return result, lines()[before:]

    def test_one_run_can_be_followed_from_start_to_end(self):
        result, new = self.run_and_read()
        self.assertEqual({line["run_id"] for line in new}, {result["run_id"]})
        self.assertEqual({line["pr_id"] for line in new}, {"ada/shop#4"})
        events = [line["event"] for line in new]
        for step in ("run.start", "github.pr_read", "rules.scored", "analysis.model_called", "analysis.prompt_built",
                     "analysis.model_answered", "manager.validated", "manager.decided", "run.end"):
            self.assertIn(step, events)

    def test_it_records_exactly_which_pull_request_and_commit_was_read(self):
        _, new = self.run_and_read()
        read = next(line for line in new if line["event"] == "github.pr_read")
        self.assertEqual((read["repo_id"], read["head_sha"], read["base_sha"], read["pr_url"], read["pr_updated_at"]),
                         (7, "a" * 40, "b" * 40, PR["html_url"], PR["updated_at"]))

    def test_a_rejected_answer_shows_the_reason_and_the_same_diff_on_the_retry(self):
        result, new = self.run_and_read(["this is not json", GOOD])
        self.assertEqual(result["attempts"], 2)
        checks = [line for line in new if line["event"] == "manager.validated"]
        self.assertEqual([c["accepted"] for c in checks], [False, True])
        self.assertEqual(checks[0]["problems"], ["Output is not valid JSON."])
        prompts = [line for line in new if line["event"] == "analysis.prompt_built"]
        self.assertEqual([p["has_feedback"] for p in prompts], [False, True])
        self.assertEqual(prompts[0]["diff_fingerprint"], prompts[1]["diff_fingerprint"])

    def test_the_account_token_is_never_written(self):
        _, new = self.run_and_read()
        self.assertNotIn(TOKEN, json.dumps(new))

    def test_keys_inside_error_text_are_masked(self):
        self.assertEqual(mask("Bearer abc def"), "*** def")
        self.assertEqual(mask(["quota for gsk_abc123", 5]), ["quota for ***", 5])
        self.assertEqual(mask(TOKEN), "***")

    def test_a_failed_read_is_logged(self):
        with mock.patch.object(analysis, "fetch_pr", side_effect=RuntimeError("github is down")):
            result, new = self.run_and_read()
        self.assertEqual(result["status"], "needs_human_review")
        self.assertIn("github.read_failed", [line["event"] for line in new])

    def test_two_runs_at_once_keep_their_own_lines(self):
        async def both():
            return await asyncio.gather(run_manager("ada/shop#4", None), run_manager("ada/shop#5", None))
        before = len(lines()) if os.path.exists(os.environ["AGENT_TRACE_FILE"]) else 0
        first, second = asyncio.run(both())
        new = lines()[before:]
        self.assertNotEqual(first["run_id"], second["run_id"])
        for line in new:
            self.assertEqual(line["pr_id"], {first["run_id"]: "ada/shop#4", second["run_id"]: "ada/shop#5"}[line["run_id"]])

    def test_the_console_line_is_one_printable_line(self):
        record = logging.LogRecord("x", logging.INFO, "", 0, "", None, None)
        record.fields = {"at": "t", "run_id": None, "pr_id": "a/b#1", "event": "e", "answer": "non‑breaking\nnext"}
        line = _ConsoleLine().format(record)
        self.assertEqual(line, "[agent -] a/b#1 e answer=non?breaking next")

    def test_a_logging_failure_never_reaches_the_agents(self):
        with mock.patch("agents.trace._setup", side_effect=OSError("disk full")):
            trace("run.start", "ada/shop#4", value=1)  # must not raise

    def test_lines_outside_a_run_have_no_run_id(self):
        with agent_run("ada/shop#4"):
            pass
        before = len(lines()) if os.path.exists(os.environ["AGENT_TRACE_FILE"]) else 0
        trace("service.delivery", "ada/shop#4")
        self.assertIsNone(lines()[before]["run_id"])


if __name__ == "__main__":
    unittest.main()
