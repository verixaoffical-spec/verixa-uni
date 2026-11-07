import json
import os
import urllib.parse as up
from contextlib import asynccontextmanager
from pathlib import Path

from cryptography.fernet import InvalidToken
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from agents.trace import add_listener

from . import analysis_api, api, auth, live, password_reset, profile, twofactor
from .agent_db import init_agent_db
from .analysis_service import HANDLED_ACTIONS, analyse_pull_request, apply_check_suite
from .db import Project, SessionLocal, get_db, init_db, now
from .security import valid_signature
from .settings import settings

# The React frontend, built with `npm run build` in the frontend folder
FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if not FRONTEND.is_dir():
    raise RuntimeError(f"{FRONTEND} is missing. Build the frontend first: cd frontend, npm install, npm run build")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()        # the five tables this app owns
    init_agent_db()  # risk_assessments, owned by the Analysis Agent
    add_listener(live.hub.publish)  # agent steps are pushed to the dashboard over a WebSocket
    yield


HTTPS = settings.public_url.startswith("https")
# The API description is a map for attackers, so it is only there on a developer's own machine.
app = FastAPI(title="Verixa", lifespan=lifespan, docs_url=None if HTTPS else "/docs", redoc_url=None,
              openapi_url=None if HTTPS else "/openapi.json")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=HTTPS,
    max_age=60 * 60 * 24 * 14,
)
MAX_BODY_BYTES = 32 * 1024 * 1024  # 50 specs at 500 KB plus a 5 MB collection, with room to spare

# Even if a script ever got into a page, the browser refuses to run it: only script files from this site are allowed.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; media-src 'self'; "
       # The live status WebSocket. Older browsers do not count ws:// and wss:// as 'self', so the address is named.
       f"connect-src 'self' {'wss' if settings.public_url.startswith('https') else 'ws'}://{up.urlsplit(settings.public_url).netloc}; "
       "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
SWAGGER_PAGE = "/docs"  # loads its scripts from a CDN, and never exists on a public address


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    """FastAPI's default answer repeats what was sent, which echoes passwords and crashes on text that cannot be encoded."""
    errors = [{"type": e["type"], "loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse({"detail": errors}, status_code=422)


@app.exception_handler(InvalidToken)
async def unreadable_secret(request: Request, exc: InvalidToken):
    """A stored token or two-step secret encrypted under a key this server does not have."""
    return JSONResponse({"detail": "Your saved sign in details could not be read. Link your account again"}, status_code=409)


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "Request is too large"}, status_code=413)
    # A chunked body declares no size and could be endless. Browsers and GitHub always send a length.
    if not length and "transfer-encoding" in request.headers:
        return JSONResponse({"detail": "Send the request with a Content-Length"}, status_code=411)
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")  # nobody can frame the log in page to steal clicks
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path != SWAGGER_PAGE:
        response.headers.setdefault("Content-Security-Policy", CSP)
    if HTTPS:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    if request.url.path.startswith(("/api/", "/auth/")):
        response.headers.setdefault("Cache-Control", "no-store")  # answers about the account stay out of every cache
    return response


app.include_router(auth.router)
app.include_router(twofactor.router)
app.include_router(profile.router)
app.include_router(password_reset.router)
app.include_router(live.router)

# Pages that depend on who is signed in are never cached, so Back after logging out cannot show them again.
NO_STORE = {"Cache-Control": "no-store"}


@app.get("/login")
@app.get("/signup")
@app.get("/forgot-password")
def auth_page(request: Request, db: Session = Depends(get_db)):
    return auth.page_redirect_if_signed_in(request, db) or FileResponse(FRONTEND / "auth.html", headers=NO_STORE)


@app.get("/reset-password")
def reset_page():
    """Open even when signed in: the link from the email must work whichever account this browser is using."""
    return FileResponse(FRONTEND / "auth.html", headers=NO_STORE)


@app.get(auth.APP)
def dashboard(request: Request, db: Session = Depends(get_db)):
    """The dashboard needs an account. Anyone else goes to log in, and comes back here afterwards."""
    if not auth.signed_in_user(request, db):
        return RedirectResponse(f"{auth.LOGIN}?next={auth.APP}")
    return FileResponse(FRONTEND / "verixa_prototype.html", headers=NO_STORE)


@app.get("/auth.html")
def auth_file():
    return RedirectResponse(auth.LOGIN)
app.include_router(api.router)
app.include_router(analysis_api.router)


def mark_verified(repo: str) -> None:
    with SessionLocal() as db:
        for project in db.scalars(select(Project).where(Project.repo == repo)):
            if not project.webhook_verified_at:
                project.webhook_verified_at = now()
        db.commit()


@app.post("/webhooks/github", status_code=202)
async def github_webhook(request: Request, background: BackgroundTasks):
    body = await request.body()
    if not valid_signature(body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "Bad signature")
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        raise HTTPException(400, "Body is not JSON")
    if not isinstance(payload, dict):
        raise HTTPException(400, "Body is not a JSON object")
    repository = payload.get("repository")
    repo = repository.get("full_name") if isinstance(repository, dict) else None
    if repo and isinstance(repo, str):
        await run_in_threadpool(mark_verified, repo)

    # Deliverable 2: a pull_request event with action opened, synchronize or reopened is handed to
    # the Analysis Agent. GitHub gives up after 10 seconds, so the analysis runs in a background
    # task and this answers 202 straight away. Repeat deliveries are filtered in the service, by
    # (project, pull request, head commit).
    event = request.headers.get("x-github-event")
    if event == "pull_request" and str(payload.get("action")) in HANDLED_ACTIONS:
        background.add_task(analyse_pull_request, payload, request.headers.get("x-github-delivery"))
    elif event == "check_suite" and payload.get("action") == "completed":
        # CI finished on a commit: a failing build or test run raises that commit's saved label to High
        background.add_task(apply_check_suite, payload)
    return {"received": event}


class PublicFiles(StaticFiles):
    """Serves the frontend folder, except the pages that have their own routes above. Windows file names ignore
    case and trailing dots, so /VERIXA_PROTOTYPE.html would otherwise reach the dashboard without the sign in check."""
    PRIVATE = [FRONTEND / "verixa_prototype.html", FRONTEND / "auth.html"]

    def lookup_path(self, path: str):
        full, stat = super().lookup_path(path)
        if stat and any(p.exists() and os.path.samefile(full, p) for p in self.PRIVATE):
            return "", None
        return full, stat


# Registered last so the routes above win. Serves the landing page and assets.
app.mount("/", PublicFiles(directory=FRONTEND, html=True), name="frontend")