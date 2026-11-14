"""Files an approved ticket in the connected Jira project, with its proof attached (Req 7.5, 7.6, 7.7).
Only called after the tester pressed Approve and file in Jira; nothing else in Verixa writes to Jira."""
from pathlib import Path

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .db import User
from .integrations import _call, _ok, atlassian_access_token

API = "https://api.atlassian.com"


def _adf(blocks: list[tuple[str, str]]) -> dict:
    """Jira's document format. blocks are (kind, text): heading, paragraph or code."""
    content = []
    for kind, text in blocks:
        if not text:
            continue
        node = {"type": "text", "text": text[:30000]}
        if kind == "heading":
            content.append({"type": "heading", "attrs": {"level": 3}, "content": [node]})
        elif kind == "code":
            content.append({"type": "codeBlock", "content": [node]})
        else:
            content.append({"type": "paragraph", "content": [node]})
    return {"type": "doc", "version": 1, "content": content}


def describe(ticket, test_title: str, error: str, pr: str, risk: str | None) -> dict:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(ticket.steps.splitlines(), 1) if s.strip())
    return _adf([
        ("paragraph", f"Found by Verixa while testing {pr} (risk {risk or 'not scored'}). Failing test: {test_title}"),
        ("heading", "Likely cause"), ("paragraph", ticket.root_cause),
        ("heading", "Steps to reproduce"), ("paragraph", steps),
        ("heading", "Error"), ("code", error[:5000]),
        ("heading", "Suggested assignee"), ("paragraph", ticket.assignee or "not suggested"),
        ("heading", "Suggested fix (text only, not applied)") if ticket.fix_text else ("paragraph", ""),
        ("code", ticket.fix_text or ""),
        ("paragraph", "Secrets such as keys, tokens and passwords were removed from the attached logs."),
    ])


def site_url(token: str, cloud_id: str) -> str | None:
    sites = _ok(_call("GET", f"{API}/oauth/token/accessible-resources", headers={"Authorization": f"Bearer {token}"}),
                "Reading the Jira site")
    return next((s.get("url") for s in sites if isinstance(s, dict) and s.get("id") == cloud_id), None)


def file_issue(db: Session, user: User, project_key: str, summary: str, description: dict, priority: str,
               attachments: list[Path]) -> tuple[str, str | None, list[str]]:
    """Creates the issue and attaches the proof. Returns (issue key, browse url, problems with attachments).
    Projects differ: some have no Bug type or no priority field, so simpler versions are tried in turn."""
    token = atlassian_access_token(db, user)
    base = f"{API}/ex/jira/{user.jira_cloud_id}/rest/api/3"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    last = None
    for issue_type in ("Bug", "Task"):
        for with_priority in (True, False):
            fields = {"project": {"key": project_key}, "summary": summary[:250], "issuetype": {"name": issue_type},
                      "description": description, "labels": ["verixa"]}
            if with_priority:
                fields["priority"] = {"name": priority}
            last = _call("POST", f"{base}/issue", headers=headers, json={"fields": fields})
            if last.status_code < 400 or last.status_code in (401, 403):
                break
        if last.status_code < 400 or last.status_code in (401, 403):
            break
    if last.status_code == 403:
        raise HTTPException(502, "Jira refused to create the ticket. Check that your account can create issues in this project")
    key = _ok(last, "Creating the Jira ticket", "Check the Jira project's issue types")["key"]

    problems = []
    for path in attachments:
        try:
            with path.open("rb") as handle:
                answer = httpx.post(f"{base}/issue/{key}/attachments", timeout=60,
                                    headers={**headers, "X-Atlassian-Token": "no-check"},
                                    files={"file": (path.name, handle)})
            if answer.status_code >= 400:
                problems.append(f"{path.name} was not attached ({answer.status_code})")
        except (httpx.HTTPError, OSError):
            problems.append(f"{path.name} was not attached")
    try:
        site = site_url(token, user.jira_cloud_id)
    except HTTPException:
        site = None
    return key, (f"{site.rstrip('/')}/browse/{key}" if site and site.startswith("https://") else None), problems
