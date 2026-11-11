import logging
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .settings import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    """A Verixa account. It starts with an email and password, or with GitHub, and links the other later."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)  # stored lowercase
    name: Mapped[str | None] = mapped_column(String(80))
    password_hash: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=now)
    github_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    github_login: Mapped[str | None] = mapped_column(String(100))
    github_name: Mapped[str | None] = mapped_column(String(200))
    github_token: Mapped[str | None] = mapped_column(Text)  # encrypted
    github_refresh: Mapped[str | None] = mapped_column(Text)  # encrypted
    github_expires_at: Mapped[int | None] = mapped_column(BigInteger)  # unix seconds, when to renew. None: never expires
    atlassian_token: Mapped[str | None] = mapped_column(Text)  # encrypted
    atlassian_refresh: Mapped[str | None] = mapped_column(Text)  # encrypted
    atlassian_expires_at: Mapped[int | None] = mapped_column(BigInteger)  # unix seconds
    jira_cloud_id: Mapped[str | None] = mapped_column(String(100))
    jira_site: Mapped[str | None] = mapped_column(String(200))
    totp_secret: Mapped[str | None] = mapped_column(Text)  # encrypted, set while two-step verification is on
    totp_pending: Mapped[str | None] = mapped_column(Text)  # encrypted, the secret being set up and not confirmed yet
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)  # the last code accepted, so none is used twice
    session_version: Mapped[int] = mapped_column(default=0, server_default="0")  # bumped to sign out every session


class RecoveryCode(Base):
    """Single use codes for when the authenticator app is lost. Only a hash is stored."""
    __tablename__ = "recovery_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(200))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordReset(Base):
    """A forgot password link. Only a hash of its token is stored, so a copy of the database cannot reset anyone."""
    __tablename__ = "password_resets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PendingSignup(Base):
    """A sign up waiting for its email to be confirmed. The account is only created in users once the link is opened.
    The password is already hashed, and only a hash of the link's token is stored."""
    __tablename__ = "pending_signups"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Project(Base):
    """One connected repository and Jira project per user."""
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    repo: Mapped[str] = mapped_column(String(200))
    jira_key: Mapped[str] = mapped_column(String(50))
    jira_name: Mapped[str] = mapped_column(String(200))
    hook_id: Mapped[int | None] = mapped_column(BigInteger)
    webhook_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SpecFile(Base):
    __tablename__ = "spec_files"
    __table_args__ = (UniqueConstraint("project_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    size: Mapped[int]
    test_count: Mapped[int]
    revision: Mapped[int] = mapped_column(default=1, server_default="1")  # bumped on every update
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Collection(Base):
    """The project's single Postman collection."""
    __tablename__ = "collections"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    size: Mapped[int]
    request_count: Mapped[int]
    revision: Mapped[int] = mapped_column(default=1, server_default="1")  # bumped on every update
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def ensure_columns() -> None:
    """create_all never alters a table that already exists, so add columns introduced after the first release."""
    existing = set(inspect(engine).get_table_names())
    if "users" in existing:
        columns = {c["name"]: c for c in inspect(engine).get_columns("users")}
        with engine.begin() as conn:
            for name, ddl in (("email", "VARCHAR(254) UNIQUE"), ("name", "VARCHAR(80)"),
                              ("password_hash", "VARCHAR(200)"), ("created_at", "TIMESTAMP WITH TIME ZONE"),
                              ("github_refresh", "TEXT"), ("github_expires_at", "BIGINT"),
                              ("totp_secret", "TEXT"), ("totp_pending", "TEXT"), ("totp_last_step", "BIGINT"),
                              ("session_version", "INTEGER NOT NULL DEFAULT 0")):
                if name not in columns:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
            # Accounts made with an email have no GitHub identity until they link one.
            for name in ("github_id", "github_login"):
                if not columns[name]["nullable"]:
                    conn.execute(text(f"ALTER TABLE users ALTER COLUMN {name} DROP NOT NULL"))
    for table in ("spec_files", "collections"):
        if table not in existing:
            continue
        if "revision" not in {c["name"] for c in inspect(engine).get_columns(table)}:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"))


def init_db() -> None:
    if engine.dialect.name == "postgresql":
        try:  # pgvector powers QA Memory next semester
            with engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception as exc:
            logging.warning("Could not enable pgvector: %s", exc)
    Base.metadata.create_all(engine)
    ensure_columns()


def get_db():
    with SessionLocal() as db:
        yield db