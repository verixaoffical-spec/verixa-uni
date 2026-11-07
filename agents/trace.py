"""Trace log for the Manager and the Analysis Agent: one line per step, so a run can be followed afterwards.

Every line carries the run_id of one run_manager call and the pull request it belongs to. Lines go to the
server console and to logs/agent_trace.jsonl. Read them with:  python scripts/agent_trace.py

A failure while logging never reaches the agents. Tokens are never passed in here, and anything that looks
like a key is masked, because provider and GitHub error messages are logged as they arrive.
AGENT_TRACE_FILE changes the file (empty turns it off). AGENT_TRACE_CONSOLE=0 silences the console.
"""
import contextvars
import hashlib
import json
import logging
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_FILE = Path(__file__).resolve().parent.parent / "logs" / "agent_trace.jsonl"
SECRET_RE = re.compile(r"gh[opsu]_\w+|github_pat_\w+|gsk_\w+|sk-[\w-]{16,}|AIza[\w-]{20,}|AKIA[0-9A-Z]{16}|Bearer\s+\S+")
PREVIEW = 500  # characters of a model's answer kept in the log

_run: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar("agent_run", default=None)
_logger = logging.getLogger("verixa.agents")


class _JsonLine(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(record.fields, default=str)


class _ConsoleLine(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        f = record.fields
        rest = " ".join(f"{k}={v}" for k, v in f.items() if k not in ("at", "run_id", "pr_id", "event"))
        text = f"[agent {f['run_id'] or '-'}] {f['pr_id'] or '-'} {f['event']} {rest}".rstrip().replace("\n", " ")
        return text.encode("ascii", "replace").decode()  # model answers can hold characters a Windows console cannot print


def _setup() -> None:
    if _logger.handlers:
        return
    _logger.setLevel(logging.INFO)
    _logger.propagate = False
    if os.getenv("AGENT_TRACE_CONSOLE", "1") != "0":
        console = logging.StreamHandler()
        console.setFormatter(_ConsoleLine())
        _logger.addHandler(console)
    path = os.getenv("AGENT_TRACE_FILE", str(DEFAULT_FILE))
    if path:
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            file = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
            file.setFormatter(_JsonLine())
            _logger.addHandler(file)
        except OSError:
            pass  # a read-only disk still gets the console
    if not _logger.handlers:
        _logger.addHandler(logging.NullHandler())


def mask(value):
    if isinstance(value, (list, tuple)):
        return [mask(item) for item in value]
    return SECRET_RE.sub("***", value) if isinstance(value, str) else value


def fingerprint(text: str | None) -> str:
    """Shows whether two runs read the same text, without storing the text."""
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()[:16]


_listeners: list = []


def add_listener(listener) -> None:
    """Calls listener(line) for every trace line, after it is masked. The backend uses this to push live status
    to the dashboard. A listener runs on whatever thread logged the line, and its errors are ignored."""
    if listener not in _listeners:
        _listeners.append(listener)


def trace(event: str, pr_id: str | None = None, **fields) -> None:
    try:
        _setup()
        run_id, run_pr = _run.get() or (None, None)
        line = {"at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "run_id": run_id,
                "pr_id": pr_id or run_pr, "event": event, **{k: mask(v) for k, v in fields.items()}}
        _logger.info(event, extra={"fields": line})
    except Exception:
        return
    for listener in list(_listeners):
        try:
            listener(line)
        except Exception:
            pass


@contextmanager
def agent_run(pr_id: str):
    """Everything logged inside belongs to one new run, including work handed to a thread."""
    run_id = uuid.uuid4().hex[:12]
    reset = _run.set((run_id, pr_id))
    try:
        yield run_id
    finally:
        _run.reset(reset)
