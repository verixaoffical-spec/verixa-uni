import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from . import analysis_api, api, auth, profile, twofactor
from .agent_db import init_agent_db
from .analysis_service import HANDLED_ACTIONS, analyse_pull_request
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
    yield


app = FastAPI(title="Verixa", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.public_url.startswith("https"),
    max_age=60 * 60 * 24 * 14,
)
MAX_BODY_BYTES = 32 * 1024 * 1024  # 50 specs at 500 KB plus a 5 MB collection, with room to spare


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "Request is too large"}, status_code=413)
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")  # nobody can frame the log in page to steal clicks
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


app.include_router(auth.router)
app.include_router(twofactor.router)
app.include_router(profile.router)

# Pages that depend on who is signed in are never cached, so Back after logging out cannot show them again.
NO_STORE = {"Cache-Control": "no-store"}


@app.get("/login")
@app.get("/signup")
def auth_page(request: Request, db: Session = Depends(get_db)):
    return auth.page_redirect_if_signed_in(request, db) or FileResponse(FRONTEND / "auth.html", headers=NO_STORE)


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
    repo = (payload.get("repository") or {}).get("full_name")
    if repo:
        await run_in_threadpool(mark_verified, repo)

    # Deliverable 2: a pull_request event with action opened, synchronize or reopened is handed to
    # the Analysis Agent. GitHub gives up after 10 seconds, so the analysis runs in a background
    # task and this answers 202 straight away. Repeat deliveries are filtered in the service, by
    # (project, pull request, head commit).
    event = request.headers.get("x-github-event")
    if event == "pull_request" and payload.get("action") in HANDLED_ACTIONS:
        background.add_task(analyse_pull_request, payload, request.headers.get("x-github-delivery"))
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