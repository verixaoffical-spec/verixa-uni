"""GitHub and Atlassian: OAuth sign in, listing repositories and projects, and webhook management."""
import time
import urllib.parse as up

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .db import User
from .security import seal, unseal
from .settings import settings

ATLASSIAN_SCOPE = "read:jira-work write:jira-work read:jira-user offline_access"
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"


def callback_url(provider: str) -> str:
    return f"{settings.public_url}/auth/{provider}/callback"


def webhook_url() -> str:
    return f"{settings.public_url}/webhooks/github"


def _call(method: str, url: str, **kwargs) -> httpx.Response:
    try:
        return httpx.request(method, url, timeout=15, **kwargs)
    except httpx.HTTPError:
        raise HTTPException(502, f"Could not reach {up.urlparse(url).netloc}")


def _ok(response: httpx.Response, what: str, hint: str = "") -> dict | list:
    if response.status_code == 401:
        raise HTTPException(401, f"{what}: please sign in again")
    if response.status_code >= 400:
        raise HTTPException(502, f"{what} failed ({response.status_code}). {hint}".strip())
    return response.json() if response.content else {}


# ---------- GitHub ----------

def _gh(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_authorize_url(state: str) -> str:
    query = up.urlencode({
        "client_id": settings.github_client_id,
        "redirect_uri": callback_url("github"),
        "scope": "repo",
        "state": state,
    })
    return f"https://github.com/login/oauth/authorize?{query}"


def github_exchange(code: str) -> tuple[str, dict]:
    response = _call("POST", "https://github.com/login/oauth/access_token", headers={"Accept": "application/json"}, data={
        "client_id": settings.github_client_id,
        "client_secret": settings.github_client_secret,
        "code": code,
        "redirect_uri": callback_url("github"),
    })
    data = _ok(response, "GitHub sign in")
    if "access_token" not in data:
        raise HTTPException(400, data.get("error_description", "GitHub sign in failed"))
    me = _ok(_call("GET", "https://api.github.com/user", headers=_gh(data["access_token"])), "GitHub profile")
    return data["access_token"], me


def list_repos(token: str) -> list[str]:
    """Repositories the user can administer, since creating a webhook needs admin access."""
    repos = _ok(_call(
        "GET", "https://api.github.com/user/repos", headers=_gh(token),
        params={"per_page": 100, "sort": "updated", "affiliation": "owner,collaborator,organization_member"},
    ), "Listing repositories")
    return [r["full_name"] for r in repos if (r.get("permissions") or {}).get("admin")]


def ensure_webhook(token: str, repo: str) -> int:
    """Creates the pull request webhook, or updates ours if it already exists, so reconnecting never duplicates it."""
    base = f"https://api.github.com/repos/{repo}/hooks"
    hint = "You need admin access to this repository."
    config = {"url": webhook_url(), "content_type": "json", "secret": settings.webhook_secret, "insecure_ssl": "0"}
    hooks = _ok(_call("GET", base, headers=_gh(token)), "Listing webhooks", hint)
    ours = next((h for h in hooks if h.get("config", {}).get("url") == webhook_url()), None)
    if ours:
        body = {"active": True, "events": ["pull_request"], "config": config}
        return _ok(_call("PATCH", f"{base}/{ours['id']}", headers=_gh(token), json=body), "Updating webhook", hint)["id"]
    body = {"name": "web", "active": True, "events": ["pull_request"], "config": config}
    return _ok(_call("POST", base, headers=_gh(token), json=body), "Creating webhook", hint)["id"]


def ping_webhook(token: str, repo: str, hook_id: int) -> None:
    _call("POST", f"https://api.github.com/repos/{repo}/hooks/{hook_id}/pings", headers=_gh(token))


def delete_webhook(token: str, repo: str, hook_id: int) -> None:
    _call("DELETE", f"https://api.github.com/repos/{repo}/hooks/{hook_id}", headers=_gh(token))  # best effort


# ---------- Atlassian ----------

def atlassian_authorize_url(state: str) -> str:
    query = up.urlencode({
        "audience": "api.atlassian.com",
        "client_id": settings.atlassian_client_id,
        "scope": ATLASSIAN_SCOPE,
        "redirect_uri": callback_url("atlassian"),
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }, quote_via=up.quote)
    return f"https://auth.atlassian.com/authorize?{query}"


def store_atlassian_tokens(user: User, tokens: dict) -> None:
    user.atlassian_token = seal(tokens["access_token"])
    if tokens.get("refresh_token"):  # Atlassian rotates refresh tokens, so always keep the newest
        user.atlassian_refresh = seal(tokens["refresh_token"])
    user.atlassian_expires_at = int(time.time()) + int(tokens.get("expires_in", 3600)) - 60


def atlassian_exchange(code: str) -> tuple[dict, dict]:
    response = _call("POST", ATLASSIAN_TOKEN_URL, json={
        "grant_type": "authorization_code",
        "client_id": settings.atlassian_client_id,
        "client_secret": settings.atlassian_client_secret,
        "code": code,
        "redirect_uri": callback_url("atlassian"),
    })
    tokens = _ok(response, "Atlassian sign in")
    sites = _ok(_call(
        "GET", "https://api.atlassian.com/oauth/token/accessible-resources",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    ), "Listing Jira sites")
    if not sites:
        raise HTTPException(400, "No Jira site found on this Atlassian account")
    return tokens, sites[0]  # the first site; a site picker can come later


def atlassian_access_token(db: Session, user: User) -> str:
    if time.time() < (user.atlassian_expires_at or 0):
        return unseal(user.atlassian_token)
    if not user.atlassian_refresh:
        raise HTTPException(401, "Atlassian sign in expired: please sign in again")
    tokens = _ok(_call("POST", ATLASSIAN_TOKEN_URL, json={
        "grant_type": "refresh_token",
        "client_id": settings.atlassian_client_id,
        "client_secret": settings.atlassian_client_secret,
        "refresh_token": unseal(user.atlassian_refresh),
    }), "Refreshing Atlassian sign in")
    store_atlassian_tokens(user, tokens)
    db.commit()
    return tokens["access_token"]


def list_jira_projects(db: Session, user: User) -> list[dict]:
    token = atlassian_access_token(db, user)
    data = _ok(_call(
        "GET", f"https://api.atlassian.com/ex/jira/{user.jira_cloud_id}/rest/api/3/project/search",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params={"maxResults": 100, "orderBy": "name"},
    ), "Listing Jira projects")
    return [{"key": p["key"], "name": p["name"]} for p in data.get("values", [])]
