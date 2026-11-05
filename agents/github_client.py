"""GitHub reads for the Analysis Agent.

Reused from multi-agents/github_client.py. One change for the consolidated app: every function
takes an optional `token`. In multi-agents the token came from a single GITHUB_TOKEN env var; here
each account has its own OAuth token, stored encrypted in `users.github_token`, so the caller
passes the decrypted token in. GITHUB_TOKEN stays as the fallback for scripts and local testing.

`create_webhook` from the original file is not included: the consolidated app creates webhooks
through backend/integrations.py (`ensure_webhook`), which already runs on the user's OAuth token.
"""
import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

API = "https://api.github.com"


def _headers(token: str | None = None) -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = token or os.getenv("GITHUB_TOKEN")
    if token:  # without one GitHub still answers for public repositories, but refuses an empty Bearer
        headers["Authorization"] = f"Bearer {token}"
    return headers


def verify_signature(body: bytes, signature: str | None) -> bool:
    """Checks the X-Hub-Signature-256 header against our webhook secret.

    Kept for parity with the original module. The consolidated app verifies webhook signatures in
    backend/security.py (`valid_signature`), which reads WEBHOOK_SECRET from settings.
    """
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if not secret or not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_pr_id(pr_id: str) -> tuple[str, int]:
    """'owner/repo#12' -> ('owner/repo', 12)"""
    repo, number = pr_id.rsplit("#", 1)
    return repo, int(number)


def fetch_pr(repo: str, number: int, token: str | None = None) -> tuple[dict, list[dict]]:
    """Returns (pr info, changed files). Each file has filename, additions, deletions, patch."""
    with httpx.Client(headers=_headers(token), timeout=20) as c:
        pr = c.get(f"{API}/repos/{repo}/pulls/{number}")
        pr.raise_for_status()
        files: list[dict] = []
        for page in range(1, 4):  # up to 300 files
            r = c.get(
                f"{API}/repos/{repo}/pulls/{number}/files",
                params={"per_page": 100, "page": page},
            )
            r.raise_for_status()
            batch = r.json()
            files += batch
            if len(batch) < 100:
                break
    return pr.json(), files


FIX_RE = re.compile(r"\b(fix(es|ed)?|bug|hotfix|patch|regression|defect)\b", re.I)


def count_fix_commits(repo: str, path: str, months: int = 12, token: str | None = None) -> int:
    """Defect history from git itself: bug-fix commits on the default branch that touched this
    folder in the last N months (merge commits are ignored). Raises on API errors."""
    since = (datetime.now(timezone.utc) - timedelta(days=30 * months)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with httpx.Client(headers=_headers(token), timeout=20) as c:
        r = c.get(f"{API}/repos/{repo}/commits", params={"path": path, "since": since, "per_page": 100})
        r.raise_for_status()
        firsts = [(x["commit"]["message"] or "").split("\n")[0] for x in r.json()]
    return sum(1 for m in firsts if not m.startswith("Merge") and FIX_RE.search(m))


def count_defects(repo: str, module: str, token: str | None = None) -> int:
    """Open or closed issues labeled 'bug' that mention the module. Raises on API errors."""
    q = f'repo:{repo} is:issue label:bug "{module}" in:title,body'
    with httpx.Client(headers=_headers(token), timeout=20) as c:
        r = c.get(f"{API}/search/issues", params={"q": q, "per_page": 1})
        r.raise_for_status()
        return r.json().get("total_count", 0)
