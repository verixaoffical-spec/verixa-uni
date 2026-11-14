"""Live run status over a WebSocket, as the SRS asks (3.4: "a WebSocket pushes live run status to the dashboard").

Every step the Manager and the Analysis Agent write to the trace log is turned into one short message and pushed to
the dashboards connected to that repository. Nothing new is stored: the trace log stays the record, and a page that
opens during a run is sent the recent messages kept in memory.

    browser  --ws-->  /api/live   (signed in session cookie, same site only)
    agents   --trace()-->  hub.publish  -->  every socket watching that repository
"""
import asyncio
import collections
import threading
import time
import urllib.parse as up

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from .db import Project, SessionLocal, User
from .settings import settings

router = APIRouter()

RECENT_SECONDS = 10 * 60  # a page opened during a run still sees how it started
RECENT_MAX = 300
QUEUE_MAX = 500           # a stalled browser drops messages instead of holding memory
ATTEMPTS = settings.agent_max_attempts


def _pr(pr_id) -> tuple[str, int] | None:
    repo, _, number = str(pr_id or "").rpartition("#")
    return (repo, int(number)) if repo and number.isdigit() else None


def describe(line: dict) -> dict | None:
    """One trace line as a short message for the dashboard, or None for steps not worth showing."""
    e, f = line.get("event"), line
    level, done = "info", False
    if e == "service.delivery":
        text = {"opened": "New pull request received from GitHub", "synchronize": "New commits pushed to the pull request",
                "reopened": "Pull request reopened"}.get(str(f.get("action")), "Pull request received from GitHub")
    elif e == "service.skipped":
        text, done = "This commit was already analysed, so it was skipped", True
    elif e == "run.start":
        text = "Manager agent started and handed the pull request to the Analysis agent"
    elif e == "github.pr_read":
        files = f.get("files")
        text = f"Analysis agent is reading the changes ({files} file{'' if str(files) == '1' else 's'})"
    elif e == "github.read_failed":
        text, level = "Analysis agent could not read the pull request from GitHub", "error"
    elif e == "github.defects_read":
        text = f"Analysis agent checked past bug fixes in {f.get('source')}: {f.get('found')} found"
    elif e == "github.defects_failed":
        text, level = f"Analysis agent could not check past bug fixes in {f.get('source')}", "warn"
    elif e == "github.ci_read":
        state = f.get("state")
        failed = ", ".join(f.get("failed") or []) if isinstance(f.get("failed"), list) else f.get("failed")
        text, level = {
            "failure": (f"Analysis agent checked CI: failing on this commit ({failed})", "warn"),
            "pending": ("Analysis agent checked CI: still running", "info"),
            "success": (f"Analysis agent checked CI: all {f.get('passed')} check(s) passed", "ok"),
        }.get(state, ("Analysis agent checked CI: no checks run on this commit", "info"))
    elif e == "github.ci_failed":
        text, level = "Analysis agent could not read the CI result", "warn"
    elif e == "ci.updated":
        done = True
        if f.get("raised") in (True, "True", "true"):
            text, level = f"CI finished and is failing, so the risk was raised to High", "warn"
        elif f.get("state") == "failure":
            text, level = "CI finished and is failing. The risk was already High", "warn"
        elif f.get("state") == "success":
            text, level = "CI finished: all checks passed", "ok"
        else:
            text = "CI result updated"
    elif e == "rules.scored":
        text = f"Risk rules scored it {f.get('risk_label')} ({f.get('score')} points)"
    elif e == "analysis.model_called":
        text = f"Analysis agent is asking the AI model ({f.get('model')}) to explain the risk"
    elif e == "analysis.model_failed":
        text, level = f"AI model {f.get('model')} did not answer, trying the next one", "warn"
    elif e == "analysis.all_models_failed":
        text, level = "No AI model could answer", "error"
    elif e == "analysis.model_answered":
        text = "AI model answered. Analysis agent sent its output to the Manager agent"
    elif e == "manager.validated":
        accepted = f.get("accepted") in (True, "True", "true")
        whose = {"test": "the Test agent's ", "test_draft": "the drafted test ", "report": "the Report agent's ",
                 "fix": "the suggested fix "}.get(str(f.get("agent")), "the ")
        text, level = ((f"Manager agent verified {whose}output", "ok") if accepted else
                       (f"Manager agent rejected {whose}output (attempt {f.get('attempt')} of {ATTEMPTS})", "warn"))
    elif e == "manager.gave_up":
        text, level = "Manager agent flagged this for a human review after every attempt", "warn"
    elif e == "manager.retry":
        text = f"Analysis agent is doing the work again (attempt {f.get('next_attempt')} of {f.get('of') or ATTEMPTS})"
    elif e == "manager.decided":
        if f.get("status") == "approved":
            text, level = f"Manager agent approved the result: {f.get('risk_label')} risk", "ok"
        else:
            text, level = "Manager agent could not approve the output. It needs a human review", "warn"
    elif e == "run.timed_out":
        text, level, done = "The analysis took too long and was stopped", "error", True
    elif e == "run.crashed":
        text, level, done = "The analysis stopped because of an error", "error", True
    elif e == "service.commit_moved":
        text, level = "A newer commit arrived while the agents were working", "warn"
    elif e == "service.saved":
        state = f.get("state")
        text, done = "Result saved", True
        level = "ok" if state == "scored" else "warn"
        if state == "needs_human_review":
            text = "Saved. It needs a human review"
        elif state == "failed":
            text, level = "Saved as failed", "error"
    elif e in ("qa.start", "qa.step"):  # the Test and Report agents, from backend/qa_service.py
        text, level, done = str(f.get("text") or ""), str(f.get("level") or "info"), f.get("done") in (True, "True", "true")
    elif e == "service.failed":
        text, level, done = "The analysis failed", "error", True
    else:
        return None
    pr = _pr(f.get("pr_id"))
    if not pr:
        return None
    return {"type": "agent", "repo": pr[0], "pr": pr[1], "run_id": f.get("run_id"), "at": f.get("at"),
            "event": e, "text": text, "level": level, "done": done}


def _put(queue: asyncio.Queue, message: dict) -> None:
    try:
        queue.put_nowait(message)
    except asyncio.QueueFull:
        pass


class Hub:
    """Routes messages from whichever thread logged them to each socket, on that socket's own event loop."""

    def __init__(self):
        self._lock = threading.Lock()
        self.sockets: dict[asyncio.Queue, tuple[str, asyncio.AbstractEventLoop]] = {}  # -> (repository, its loop)
        self.recent: collections.deque = collections.deque(maxlen=RECENT_MAX)

    def publish(self, line: dict) -> None:
        """Called by the trace log for every line, possibly from a worker thread."""
        message = describe(line)
        if not message:
            return
        with self._lock:
            self.recent.append((time.monotonic(), message))
            targets = [(queue, loop) for queue, (repo, loop) in self.sockets.items() if repo == message["repo"]]
        for queue, loop in targets:
            if not loop.is_closed():
                loop.call_soon_threadsafe(_put, queue, message)

    def add(self, queue: asyncio.Queue, repo: str) -> list[dict]:
        """Starts delivering to a socket, and returns what happened on its repository in the last minutes."""
        cutoff = time.monotonic() - RECENT_SECONDS
        with self._lock:
            self.sockets[queue] = (repo, asyncio.get_running_loop())
            return [{**m, "replay": True} for at, m in self.recent if at >= cutoff and m["repo"] == repo]

    def remove(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self.sockets.pop(queue, None)


hub = Hub()


def _watched_repo(session: dict) -> str | None:
    """The repository of the signed in account: None when nobody is signed in, "" when nothing is connected."""
    uid = session.get("uid")
    if not uid:
        return None
    with SessionLocal() as db:
        user = db.get(User, uid)
        if not user or session.get("ver", 0) != user.session_version:
            return None
        project = db.scalar(select(Project).where(Project.user_id == user.id))
        return project.repo if project else ""


def _same_site(ws: WebSocket) -> bool:
    """Browsers always send Origin on a WebSocket. Another site must not open one with this site's cookie."""
    origin = ws.headers.get("origin")
    if not origin:
        return False
    return up.urlsplit(origin).netloc in {ws.headers.get("host"), up.urlsplit(settings.public_url).netloc}


@router.websocket("/api/live")
async def live(ws: WebSocket):
    if not _same_site(ws):
        await ws.close(code=1008)
        return
    repo = await run_in_threadpool(_watched_repo, dict(ws.session))
    if repo is None:
        # Accepted first: a browser only sees the close code of an accepted socket, and 4401 tells the
        # dashboard to send the person to log in instead of reconnecting.
        await ws.accept()
        await ws.close(code=4401)
        return
    await ws.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
    earlier = hub.add(queue, repo) if repo else []

    async def pump():
        for message in earlier:
            await ws.send_json(message)
        while True:
            await ws.send_json(await queue.get())

    sender = asyncio.create_task(pump())
    try:
        while True:
            await ws.receive_text()  # the page pings to keep tunnels open; a close ends this loop
    except WebSocketDisconnect:
        pass
    except RuntimeError:  # the socket closed while the server was sending
        pass
    finally:
        sender.cancel()
        hub.remove(queue)
