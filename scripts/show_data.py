"""Prints what the app has stored in the database, newest first, to check by eye that data arrives. Read only.

    .venv\\Scripts\\python.exe scripts\\show_data.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the Windows console cannot print every character in an email

from sqlalchemy import func, select  # noqa: E402

from backend.db import Collection, Project, RecoveryCode, SessionLocal, SpecFile, User, engine  # noqa: E402


def when(d) -> str:
    return d.strftime("%Y-%m-%d %H:%M") if d else "-"


with SessionLocal() as db:
    print(f"Database: {engine.url.render_as_string(hide_password=True)}\n")
    for model in (User, RecoveryCode, Project, SpecFile, Collection):
        print(f"{model.__tablename__:<15} {db.scalar(select(func.count()).select_from(model))} rows")

    print("\nLatest users")
    for u in db.scalars(select(User).order_by(User.id.desc()).limit(10)):
        print(f"  {u.id:>4}  {u.email or '-':<34} {u.name or '-':<20} github={u.github_login or '-':<15} "
              f"jira={u.jira_site or '-':<25} 2fa={'on' if u.totp_secret else 'off'}  created {when(u.created_at)}")

    print("\nProjects")
    for p in db.scalars(select(Project).order_by(Project.id.desc()).limit(10)):
        print(f"  {p.id:>4}  user={p.user_id:<4} repo={p.repo:<30} jira={p.jira_key:<8} "
              f"webhook verified {when(p.webhook_verified_at)}")

    print("\nSpec files")
    for s in db.scalars(select(SpecFile).order_by(SpecFile.id.desc()).limit(10)):
        print(f"  {s.id:>4}  project={s.project_id:<4} {s.name:<35} {s.test_count} tests  rev {s.revision}  {when(s.created_at)}")

    print("\nCollections")
    for c in db.scalars(select(Collection).order_by(Collection.id.desc()).limit(10)):
        print(f"  {c.id:>4}  project={c.project_id:<4} {c.name:<35} {c.request_count} requests  rev {c.revision}  {when(c.created_at)}")
