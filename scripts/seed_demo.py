"""Fills a local SQLite database with demo accounts, so every screen can be tried without GitHub or Jira keys.

Run with:  python -m scripts.seed_demo     Refuses anything but SQLite, so it can never touch the shared database.
"""
import sys

from sqlalchemy import select

from backend.accounts import hash_password
from backend.agent_db import AgentBase, RiskAssessment, dump, init_agent_db
from backend.db import Base, Project, SessionLocal, User, engine, init_db
from backend.security import seal

PASSWORD = "Verixa-Demo-2026"
XSS = "<img src=x onerror=alert('xss')>"


def assessment(project: Project, number: int, state: str, label: str | None, title: str, **extra) -> RiskAssessment:
    return RiskAssessment(
        project_id=project.id, repo=project.repo, pr_number=number, head_sha=f"{number:07x}abcdef", state=state,
        risk_label=label, base_label=label, title=title, pr_url=f"https://github.com/{project.repo}/pull/{number}",
        author="demo-dev", **extra)


def main() -> None:
    if engine.dialect.name != "sqlite":
        sys.exit("Refusing to run: DATABASE_URL must be a local SQLite file, because this replaces every table.")
    AgentBase.metadata.drop_all(engine)
    Base.metadata.drop_all(engine)
    init_db()
    init_agent_db()

    with SessionLocal() as db:
        for email, name, repo in (("demo@verixa.dev", "Demo Tester", "demo/shop"), ("other@verixa.dev", "Other Tester", "other/shop")):
            # The tokens are placeholders: they get past "link GitHub first", and GitHub itself will refuse them.
            user = User(email=email, name=name, password_hash=hash_password(PASSWORD), github_token=seal("demo"),
                        atlassian_token=seal("demo"), github_login=name.split()[0].lower(), jira_site="demo.atlassian.net",
                        atlassian_expires_at=4102444800)
            db.add(user)
            db.flush()
            db.add(Project(user_id=user.id, repo=repo, jira_key="QA", jira_name="QA Board"))
        db.flush()

        project = db.scalar(select(Project).where(Project.repo == "demo/shop"))
        factors = dump(["size: 3 file(s), 160 lines changed (3 pts)", "sensitive area: high (2 pts)", "score 5 gives Medium, raised to High"])
        db.add_all([
            assessment(project, 1, "scored", "High", "Refactor checkout session", score=7, files_changed=3, lines_changed=160,
                       past_defects=2, sensitivity="high", module="payments", risk_factors=factors,
                       reasoning="The change rewrites how a checkout session is charged, so a mistake costs real money.",
                       test_areas=dump(["charge succeeds with a valid card", "expired card is declined"]), model_used="demo", attempts=1),
            assessment(project, 2, "scored", "Medium", "Update profile page", score=5, files_changed=2, lines_changed=40,
                       module="profile", risk_factors=dump(["size: 2 file(s), 40 lines changed (2 pts)"]), attempts=1),
            assessment(project, 3, "scored", "Low", "Fix a typo in the footer", score=2, files_changed=1, lines_changed=2,
                       module="root", attempts=1),
            assessment(project, 4, "needs_human_review", "High", "Rotate signing keys", score=8, attempts=3,
                       errors=dump(["reasoning must be 2-3 sentences."])),
            assessment(project, 5, "failed", None, "Could not be analysed", errors=dump(["The analysis could not finish: RuntimeError"])),
            # Hostile text from a pull request. It must show as plain text, and no alert may ever appear.
            assessment(project, 6, "scored", "High", XSS, score=7, module=XSS, risk_factors=dump([XSS]), reasoning=XSS,
                       test_areas=dump([XSS]), model_used=XSS, attempts=1),
        ])
        db.commit()
    print(f"Done. Log in as demo@verixa.dev or other@verixa.dev with the password {PASSWORD}")


if __name__ == "__main__":
    main()
