"""The Manager's loop for the Test and Report agents (Req 4.10, 5.6, 7.9, 9.4).

The same pattern as the Analysis Manager in manager.py: hand the work to a worker, check the answer with plain code,
send it back with the problems as feedback, and give up after AGENT_MAX_ATTEMPTS so a person can look (BR7).
"""
import os
from collections.abc import Awaitable, Callable

from .trace import trace

MAX_ATTEMPTS = max(1, int(os.getenv("AGENT_MAX_ATTEMPTS", "3")))  # TBD3, the same limit as the Analysis Manager


async def supervise(agent: str, work: Callable[[str | None], Awaitable], check: Callable[[object], list[str]],
                    pr_id: str | None = None, attempts: int = MAX_ATTEMPTS):
    """Runs work(feedback) until check(answer) finds no problems.
    Returns (answer, attempts used, problems). answer is None when the Manager could not accept any attempt."""
    feedback, problems = None, ["the worker produced nothing"]
    for n in range(1, attempts + 1):
        try:
            answer = await work(feedback)
            problems = check(answer)
        except Exception as exc:  # a model that is down, or an answer that is not JSON
            answer, problems = None, [f"{type(exc).__name__}: {str(exc)[:200]}"]
        trace("manager.validated", pr_id, agent=agent, attempt=n, accepted=not problems, problems=problems)
        if not problems:
            return answer, n, []
        feedback = "; ".join(problems)
    trace("manager.gave_up", pr_id, agent=agent, attempts=attempts, problems=problems)
    return None, attempts, problems
