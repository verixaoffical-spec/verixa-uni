"""GitHub and Atlassian: OAuth sign in, listing repositories and projects, and webhook management."""
import threading
import time
import urllib.parse as up

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .db import User
from .security import seal, unseal
from .settings import settings

GITHUB_SCOPE = "repo offline_access"  # offline_access asks for a refresh token, and adds no prompt
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_EARLY_SECONDS = 10 * 60  # renew this early, so a token never expires during an agent run, which can take 5 minutes
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
    if response.status_code == 401:  # the saved token is no good. Not a 401: the Verixa session itself is fine
        raise HTTPException(409, f"{what}: the saved sign in no longer works. Link your account again")
    if response.status_code >= 400:
        raise HTTPException(502, f"{what} failed ({response.status_code}). {hint}".strip())
    try:
        return response.json() if response.content else {}
    except ValueError:
        raise HTTPException(502, f"{what} failed. The answer could not be read")


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
        "scope": GITHUB_SCOPE,
        "state": state,
    })
    return f"https://github.com/login/oauth/authorize?{query}"


def github_exchange(code: str) -> tuple[dict, dict]:
    response = _call("POST", GITHUB_TOKEN_URL, headers={"Accept": "application/json"}, data={
        "client_id": settings.github_client_id,
        "client_secret": settings.github_client_secret,
        "code": code,
        "redirect_uri": callback_url("github"),
    })
    data = _ok(response, "GitHub sign in")
    if "access_token" not in data:
        raise HTTPException(400, data.get("error_description", "GitHub sign in failed"))
    me = _ok(_call("GET", "https://api.github.com/user", headers=_gh(data["access_token"])), "GitHub profile")
    return data, me


def store_github_tokens(user: User, tokens: dict) -> None:
    """A token with no expires_in does not expire, so it has no refresh token either."""
    user.github_token = seal(tokens["access_token"])
    user.github_refresh = seal(tokens["refresh_token"]) if tokens.get("refresh_token") else None
    expires_in = tokens.get("expires_in")
    user.github_expires_at = int(time.time()) + int(expires_in) - GITHUB_EARLY_SECONDS if expires_in else None


def _github_token_is_fresh(user: User) -> bool:
    return not user.github_expires_at or time.time() < user.github_expires_at


_github_refresh_lock = threading.Lock()


def github_access_token(db: Session, user: User) -> str:
    """The account's GitHub token, renewed first if it is about to expire. A refresh token works only once, so only
    one request may renew at a time: the lock covers this server and the row lock covers any other server."""
    if _github_token_is_fresh(user):
        return unseal(user.github_token)
    with _github_refresh_lock:
        db.refresh(user, with_for_update=True)
        if _github_token_is_fresh(user):  # another request renewed it while this one waited
            token = unseal(user.github_token)
            db.commit()
            return token
        if not user.github_refresh:
            db.rollback()
            raise HTTPException(409, "GitHub sign in expired. Link your account again")
        refresh_token = unseal(user.github_refresh)
        try:
            response = _call("POST", GITHUB_TOKEN_URL, headers={"Accept": "application/json"}, data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            })
            try:
                answer = response.json()
            except ValueError:
                answer = {}
            if isinstance(answer, dict) and answer.get("error"):  # for example bad_refresh_token, after six months unused
                raise HTTPException(409, "GitHub sign in expired. Link your account again")
            tokens = _ok(response, "Refreshing GitHub sign in")
            if not isinstance(tokens, dict) or "access_token" not in tokens:
                raise HTTPException(502, "Refreshing GitHub sign in failed. The answer could not be read")
        except HTTPException:
            db.rollback()
            raise
        store_github_tokens(user, tokens)
        db.commit()  # the old tokens stopped working the moment GitHub answered, so save the new ones straight away
        return tokens["access_token"]


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
        raise HTTPException(409, "Atlassian sign in expired. Link your account again")
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
