"""Drives the Analysis Manager through the ADK runner.

Reused from multi-agents/runner.py. Two changes for the consolidated app:
  * imports come from this package instead of the top-level `manager_agent` module
  * `run_manager` takes the account's GitHub token and seeds it into the agent state, so the
    Analysis Agent reads the pull request as the account that connected the repository
"""
import logging

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .analysis import ANALYSES
from .manager import root_agent

log = logging.getLogger(__name__)

APP, USER = "verixa", "system"
_service = InMemorySessionService()
_runner = Runner(agent=root_agent, app_name=APP, session_service=_service)


async def run_manager(pr_id: str, token: str | None = None) -> dict:
    """Runs the manager -> Analysis Agent loop for one pull request and returns its result dict."""
    ANALYSES.setdefault(pr_id, {})["token"] = token
    session = await _service.create_session(app_name=APP, user_id=USER)
    msg = types.Content(role="user", parts=[types.Part(text=f"Analyze {pr_id}")])
    async for event in _runner.run_async(user_id=USER, session_id=session.id, new_message=msg):
        if event.content and event.content.parts and event.content.parts[0].text:
            log.info("[%s] %s: %s", pr_id, event.author, event.content.parts[0].text[:140])
    return (ANALYSES.get(pr_id) or {}).get("result") or {
        "pr_id": pr_id, "status": "needs_human_review", "attempts": 0,
        "errors": ["no result produced"], "analysis": None}
