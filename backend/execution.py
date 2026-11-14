"""The Test Agent's hands (UC4, UC6): checks staging, runs Playwright and Newman in a locked down process, and turns
their reports into results with evidence.

Uploaded test code runs on this server, so every run:
  * gets its own empty folder under runner/runs, deleted afterwards
  * starts with an environment holding only what Node needs: no .env values, tokens or database address
  * is stopped, with every child process, after RUN_TIMEOUT_SECONDS
  * may only import @playwright/test (backend/validators.py refuses everything else at upload)
"""
import ipaddress
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import urllib.parse as up
import zipfile
from pathlib import Path

import httpx

from agents.redact import hide_secrets

from .settings import settings
from .validators import analyse_spec

ROOT = Path(__file__).resolve().parent.parent
RUNNER = (ROOT / settings.runner_dir).resolve()
EVIDENCE = (ROOT / settings.evidence_dir).resolve()
PLAYWRIGHT_CLI = RUNNER / "node_modules" / "@playwright" / "test" / "cli.js"
NEWMAN_CLI = RUNNER / "node_modules" / "newman" / "bin" / "newman.js"

# A failure that says nothing about the code: the network or the machine was slow (Req 4.6, BR5)
TEMPORARY = re.compile(r"Test timeout of \d+ms exceeded|net::ERR_|ECONNRESET|ECONNREFUSED|ETIMEDOUT|ESOCKETTIMEDOUT|"
                       r"EAI_AGAIN|socket hang up|page\.goto: Timeout|browserContext\.newPage: Timeout", re.I)
NEWMAN_TEMPORARY = {"ETIMEDOUT", "ECONNRESET", "ECONNREFUSED", "ESOCKETTIMEDOUT", "EAI_AGAIN", "EPIPE"}
GOTO = re.compile(r"""\.goto\(\s*(['"`])([^'"`$]*)\1""")
ENV_KEEP = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "USERPROFILE",
            "HOME", "PLAYWRIGHT_BROWSERS_PATH", "LANG")


class RunError(Exception):
    """The run cannot go on, with a message for the tester."""


# ---------- the staging address (Req 4.4, BR8) ----------

def staging_problem(url: str) -> str | None:
    """Why this address cannot be used as staging, or None. Called when it is saved and again before every run."""
    if not isinstance(url, str) or not url.strip():
        return "Enter the staging address, for example https://staging.example.com"
    if len(url) > 500:
        return "The address is too long"
    parts = up.urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "Use an http:// or https:// address"
    if parts.username or parts.password:
        return "Leave the user name and password out of the address"
    if parts.query or parts.fragment:
        return "Leave ? and # parts out of the address"
    public = up.urlsplit(settings.public_url)
    if parts.hostname == public.hostname and (parts.port or 0) == (public.port or 0):
        return "That is the Verixa server itself. Enter the address of the app you test"
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)}
    except (socket.gaierror, UnicodeError, ValueError):
        return f"{parts.hostname} could not be found. Check the address"
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        ip = getattr(ip, "ipv4_mapped", None) or ip  # ::ffff:169.254.169.254 is the same machine as 169.254.169.254
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or (ip.is_reserved and not ip.is_loopback):
            return "That address is not allowed"  # 169.254.169.254 is where cloud servers keep their own keys
        if not settings.allow_private_staging and (ip.is_private or ip.is_loopback):
            return "Private network addresses are turned off on this server (ALLOW_PRIVATE_STAGING)"
    return None


def clean_staging(url: str) -> str:
    return url.strip().rstrip("/")


def probe(url: str) -> int | None:
    """The status code of a GET, or None when nothing answered. Redirects are not followed, so a check cannot be
    bounced to an address the tester never entered."""
    try:
        return httpx.get(url, timeout=settings.staging_probe_seconds, follow_redirects=False).status_code
    except (httpx.HTTPError, ValueError):
        return None


def deployment_check(staging: str, specs: dict[str, str]) -> tuple[set[str], dict[str, str]]:
    """Asks staging for every page each spec opens (Req 4.5). A spec whose pages all answer 404 is not deployed yet,
    so it is marked deployment pending and not run. Returns (specs to run, {pending spec: reason}).
    Raises RunError when staging does not answer at all."""
    if probe(staging + "/") is None:
        raise RunError(f"Staging at {staging} is not answering. Start it, or fix the address on Integrations")
    host = up.urlsplit(staging).netloc
    run, pending, seen = set(), {}, {}
    for name, text in specs.items():
        paths = []
        for _, target in GOTO.findall(text):
            if target.startswith("/"):
                paths.append(target)
            elif up.urlsplit(target).netloc == host:
                paths.append(up.urlsplit(target).path or "/")
        if not paths:  # opens no page of staging that can be checked, so it runs
            run.add(name)
            continue
        missing = []
        for path in dict.fromkeys(paths):
            if path not in seen:
                seen[path] = probe(staging + path)
            if seen[path] == 404:
                missing.append(path)
        if len(missing) == len(set(paths)):
            pending[name] = f"{', '.join(missing[:3])} answered 404 on staging, so this is not deployed yet"
        else:
            run.add(name)
    return run, pending


# ---------- running node in a locked down process ----------

def _child_env() -> dict:
    env = {k: os.environ[k] for k in ENV_KEEP if k in os.environ}
    env["CI"] = "1"  # no interactive report server
    env["NODE_OPTIONS"] = "--max-old-space-size=1024"
    return env


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_node(args: list[str], cwd: Path, timeout: float) -> tuple[int | None, str]:
    """Runs node with the given script and arguments. Returns (exit code or None on time out, the last of its output)."""
    proc = subprocess.Popen([settings.node_command, *args], cwd=cwd, env=_child_env(), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=os.name != "nt",
                            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out.decode("utf-8", "replace")[-4000:]
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        proc.communicate()
        return None, "stopped: the run took longer than the time limit"


def tools_ready() -> str | None:
    if not PLAYWRIGHT_CLI.exists() or not NEWMAN_CLI.exists():
        return f"Test tools are not installed. Run npm install in {RUNNER}"
    if not shutil.which(settings.node_command):
        return "Node.js is not installed on the server"
    return None


def workspace(run_id: int) -> Path:
    """A fresh folder inside runner/, so the specs find @playwright/test in runner/node_modules."""
    folder = RUNNER / "runs" / f"run_{int(run_id)}"
    shutil.rmtree(folder, ignore_errors=True)
    (folder / "specs").mkdir(parents=True)
    return folder


def write_playwright(folder: Path, staging: str, specs: dict[str, str]) -> None:
    for name, text in specs.items():
        target = (folder / "specs" / name).resolve()
        if target.parent != (folder / "specs").resolve():  # names were checked at upload; this is a second lock
            raise RunError(f"Unsafe file name {name!r}")
        target.write_text(text, encoding="utf-8")
    config = {
        "testDir": "./specs", "outputDir": "./output", "timeout": settings.test_timeout_ms,
        "retries": 1,  # a failure gets one more attempt, so a temporary error is retried once (Req 4.7)
        "workers": 2, "reporter": [["json", {"outputFile": "report.json"}]],
        "use": {"baseURL": staging, "headless": True, "screenshot": "only-on-failure", "trace": "retain-on-failure"},
    }
    (folder / "playwright.config.mjs").write_text(
        "import { defineConfig } from '@playwright/test';\nexport default defineConfig(" + json.dumps(config) + ");\n",
        encoding="utf-8")


def run_playwright(folder: Path) -> dict:
    code, out = run_node([str(PLAYWRIGHT_CLI), "test", "--config", "playwright.config.mjs"], folder,
                         settings.run_timeout_seconds)
    report = folder / "report.json"
    if code is None:
        raise RunError("The Playwright tests did not finish within the time limit")
    if not report.exists():
        raise RunError("Playwright did not produce a report: " + hide_secrets(out[-600:])[0])
    return json.loads(report.read_text(encoding="utf-8"))


def run_newman(folder: Path, staging: str, collection_text: str, name: str = "newman.json") -> dict:
    (folder / "collection.json").write_text(collection_text, encoding="utf-8")
    args = [str(NEWMAN_CLI), "run", "collection.json", "--env-var", f"baseUrl={staging}", "--reporters", "json",
            "--reporter-json-export", name, "--timeout-request", str(settings.test_timeout_ms), "--disable-unicode"]
    code, out = run_node(args, folder, settings.run_timeout_seconds)
    if code is None:
        raise RunError("The Newman API tests did not finish within the time limit")
    report = folder / name
    if not report.exists():
        raise RunError("Newman did not produce a report: " + hide_secrets(out[-600:])[0])
    return json.loads(report.read_text(encoding="utf-8"))


# ---------- reading the reports ----------

def _walk_suites(suite: dict, path: list[str]):
    title = suite.get("title") or ""
    here = path + ([title] if title and not title.endswith(".ts") else [])
    for spec in suite.get("specs") or []:
        yield here, spec
    for child in suite.get("suites") or []:
        yield from _walk_suites(child, here)


def playwright_results(report: dict) -> list[dict]:
    """One dict per test: kind, file, title, outcome, retried, error, ms, attachments (name -> path), output."""
    found = []
    for top in report.get("suites") or []:
        for path, spec in _walk_suites(top, []):
            for test in spec.get("tests") or []:
                attempts = test.get("results") or []
                last = attempts[-1] if attempts else {}
                status = test.get("status")
                error = (last.get("error") or {}).get("message") or ""
                if status == "skipped":
                    outcome = "skipped"
                elif status in ("expected", "flaky"):
                    outcome = "passed"
                elif TEMPORARY.search(error):
                    outcome = "temporary_error"  # still failing after its one retry (TBD5): stays temporary
                else:
                    outcome = "real_bug"
                attachments = {}
                for result in attempts:  # the last failed attempt's files win
                    for a in result.get("attachments") or []:
                        if a.get("path") and a.get("name") in ("screenshot", "trace"):
                            attachments[a["name"]] = a["path"]
                output = "".join((o.get("text") or "") for r in attempts for o in (r.get("stdout") or []) + (r.get("stderr") or []))
                found.append({
                    "kind": "playwright", "file": spec.get("file") or top.get("file") or "",
                    "title": " › ".join(path + [spec.get("title") or "untitled"])[:500], "outcome": outcome,
                    "retried": len(attempts) > 1, "error": re.sub(r"\x1b\[[0-9;]*m", "", error)[:4000],
                    "ms": sum(int(r.get("duration") or 0) for r in attempts), "attachments": attachments, "output": output,
                })
    return found


def _folder_names(items: list, path: list[str], out: dict) -> None:
    for item in items or []:
        if isinstance(item, dict) and isinstance(item.get("item"), list):
            _folder_names(item["item"], path + [str(item.get("name") or "")], out)
        elif isinstance(item, dict):
            out[item.get("id") or item.get("name")] = " / ".join(path)


def newman_results(report: dict, collection_name: str) -> list[dict]:
    run = report.get("run") or {}
    folders: dict = {}
    _folder_names((report.get("collection") or {}).get("item") or [], [], folders)
    found = []
    for ex in run.get("executions") or []:
        item = ex.get("item") or {}
        request = ex.get("request") or {}
        response = ex.get("response") or {}
        url = request.get("url")
        if isinstance(url, dict):  # newman's report splits the address into its parts
            port = f":{url['port']}" if url.get("port") else ""
            url = f"{url.get('protocol') or 'http'}://{'.'.join(url.get('host') or [])}{port}/{'/'.join(url.get('path') or [])}"
        method, code = request.get("method") or "GET", response.get("code")
        failed = [a for a in ex.get("assertions") or [] if a.get("error")]
        req_error = ex.get("requestError") or {}
        if req_error:
            outcome = "temporary_error" if req_error.get("code") in NEWMAN_TEMPORARY else "real_bug"
            error = f"{req_error.get('code') or 'Request failed'}: {req_error.get('message') or ''}"
        elif failed and code == 404:
            outcome, error = "deployment_pending", f"{method} answered 404, so this endpoint is not on staging yet"
        elif failed:
            outcome = "real_bug"
            error = "; ".join(f"{a.get('assertion')}: {(a.get('error') or {}).get('message')}" for a in failed)
        elif isinstance(code, int) and code >= 500:
            outcome, error = "real_bug", f"The server answered {code}"
        else:
            outcome, error = "passed", ""
        body = response.get("stream")
        if isinstance(body, dict) and isinstance(body.get("data"), list):
            try:
                body = bytes(body["data"][:4000]).decode("utf-8", "replace")
            except (TypeError, ValueError):
                body = ""
        found.append({
            "kind": "newman", "file": folders.get(item.get("id") or item.get("name")) or collection_name,
            "title": str(item.get("name") or "request")[:500], "outcome": outcome, "retried": False,
            "error": error[:4000], "ms": int(response.get("responseTime") or 0), "attachments": {},
            "network": f"{method} {url} -> {code if code is not None else 'no answer'} "
                       f"({response.get('responseTime', '?')} ms)\n\n{body if isinstance(body, str) else ''}"[:6000],
        })
    return found


def merge_newman_retry(first: list[dict], second: list[dict]) -> list[dict]:
    """A request that hit a temporary error takes its result from the second run, once (Req 4.7)."""
    again = {(r["file"], r["title"]): r for r in second}
    merged = []
    for r in first:
        retry = again.get((r["file"], r["title"])) if r["outcome"] == "temporary_error" else None
        merged.append({**retry, "retried": True} if retry else r)
    return merged


def spec_titles(text: str) -> list[str]:
    return [t["title"] for t in analyse_spec(text)["tests"]]


# ---------- evidence (UC6) ----------

def _trace_logs(trace_zip: Path) -> tuple[str, str]:
    """The console messages and network requests recorded in a Playwright trace."""
    console, network = [], []
    try:
        with zipfile.ZipFile(trace_zip) as z:
            for name in z.namelist():
                if not name.endswith((".trace", ".network")) or z.getinfo(name).file_size > 50_000_000:
                    continue
                for line in z.read(name).decode("utf-8", "replace").splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("type") == "console":
                        console.append(f"[{event.get('messageType', 'log')}] {event.get('text', '')}")
                    elif event.get("type") == "resource-snapshot":
                        snap = event.get("snapshot") or {}
                        req, res = snap.get("request") or {}, snap.get("response") or {}
                        network.append(f"{req.get('method', '?')} {req.get('url', '?')} -> {res.get('status', '?')}")
    except (zipfile.BadZipFile, OSError):
        pass
    return "\n".join(console[-500:]), "\n".join(network[-1000:])


def save_evidence(run_id: int, result_id: int, folder: Path, result: dict) -> list[tuple[str, str]]:
    """Copies the proof of one failed test next to the others of its run. Text logs are saved with secrets hidden
    (Req 7.3). Returns [(evidence_type, path relative to EVIDENCE)]."""
    target = EVIDENCE / str(int(run_id)) / str(int(result_id))
    target.mkdir(parents=True, exist_ok=True)
    saved = []
    console = result.get("output") or ""  # the error itself is shown on its own; this is what the test printed
    network = result.get("network") or ""
    for kind, source in (result.get("attachments") or {}).items():
        path = Path(source)
        if not path.is_absolute():
            path = folder / path
        path = path.resolve()
        if not path.is_file() or folder.resolve() not in path.parents:  # only files the run itself made
            continue
        name = "screenshot.png" if kind == "screenshot" else "trace.zip"
        shutil.copyfile(path, target / name)
        saved.append((kind, f"{run_id}/{result_id}/{name}"))
        if kind == "trace":
            more_console, network_log = _trace_logs(path)
            console += ("\n\nBrowser console:\n" + more_console) if more_console else ""
            network = network_log or network
    console = console.strip() or (result.get("error") or "")  # nothing printed: keep the error, so the ticket has a log
    for kind, text in (("console_log", console), ("network_log", network)):
        if text.strip():
            (target / f"{kind}.txt").write_text(hide_secrets(text)[0], encoding="utf-8")
            saved.append((kind, f"{run_id}/{result_id}/{kind}.txt"))
    return saved


def evidence_file(relative: str) -> Path | None:
    """The file behind a stored evidence path, only if it really is inside the evidence folder."""
    path = (EVIDENCE / relative).resolve()
    return path if EVIDENCE in path.parents and path.is_file() else None


def remove_run_files(run_ids: list[int]) -> None:
    for run_id in run_ids:
        shutil.rmtree(EVIDENCE / str(int(run_id)), ignore_errors=True)
        shutil.rmtree(RUNNER / "runs" / f"run_{int(run_id)}", ignore_errors=True)
