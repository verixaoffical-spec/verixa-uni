"""Drives the Analysis Manager through the ADK runner.

Reused from multi-agents/runner.py. Two changes for the consolidated app:
  * imports come from this package instead of the top-level `manager_agent` module
  * `run_manager` takes the account's GitHub token and seeds it into the agent state, so the
    Analysis Agent reads the pull request as the account that connected the repository
"""
import asyncio
import os
import time

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .analysis import ANALYSES
from .manager import root_agent
from .trace import agent_run, trace

APP, USER = "verixa", "system"


def run_timeout() -> float:
    """Seconds a whole run may take, across every attempt and model, before it is given up as failed."""
    return float(os.getenv("AGENT_RUN_TIMEOUT", "300"))


_service = InMemorySessionService()
_runner = Runner(agent=root_agent, app_name=APP, session_service=_service)


async def run_manager(pr_id: str, token: str | None = None) -> dict:
    """Runs the manager -> Analysis Agent loop for one pull request and returns its result dict."""
    ANALYSES.setdefault(pr_id, {})["token"] = token
    started = time.perf_counter()
    with agent_run(pr_id) as run_id:
        trace("run.start")
        try:
            session = await _service.create_session(app_name=APP, user_id=USER)
            msg = types.Content(role="user", parts=[types.Part(text=f"Analyze {pr_id}")])
            async with asyncio.timeout(run_timeout()):
                async for _ in _runner.run_async(user_id=USER, session_id=session.id, new_message=msg):
                    pass
        except TimeoutError as exc:
            message = f"The analysis did not finish within {run_timeout():g} seconds"
            trace("run.timed_out", error=message, ms=round((time.perf_counter() - started) * 1000))
            raise TimeoutError(message) from exc
        except Exception as exc:
            trace("run.crashed", error=f"{type(exc).__name__}: {str(exc)[:300]}", ms=round((time.perf_counter() - started) * 1000))
            raise
        result = (ANALYSES.get(pr_id) or {}).get("result") or {
            "pr_id": pr_id, "status": "needs_human_review", "attempts": 0,
            "errors": ["no result produced"], "analysis": None}
        trace("run.end", status=result["status"], attempts=result["attempts"], ms=round((time.perf_counter() - started) * 1000))
    return {**result, "run_id": run_id}
