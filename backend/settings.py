from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    public_url: str = "http://localhost:8000"
    secret_key: str
    webhook_secret: str
    database_url: str = "postgresql+psycopg://verixa:verixa@localhost:5432/verixa"
    totp_encryption_key: str = ""  # a Fernet key for two-step verification secrets, see .env.example

    # Email for forgot password links. With SMTP_HOST empty, the link is printed in the server console instead.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = ""

    github_client_id: str
    github_client_secret: str
    atlassian_client_id: str
    atlassian_client_secret: str

    # ---- Test runs (UC4 to UC7). Every limit can be changed in .env, nothing is fixed in code ----
    agent_max_attempts: int = 3          # TBD3: how often the Manager sends work back before a person must look
    run_timeout_seconds: int = 600       # a whole run (Playwright and Newman together) is stopped after this
    test_timeout_ms: int = 30_000        # one Playwright test
    staging_probe_seconds: float = 8     # the "is it on staging" check of one address
    max_runs_per_hour: int = 20          # per account, so nobody can keep the server busy running tests
    runner_dir: str = "runner"           # holds node_modules with @playwright/test and newman (npm install there)
    evidence_dir: str = "runner/evidence"
    node_command: str = "node"
    # Staging may be a computer on the local network while developing. Cloud metadata addresses are always refused.
    allow_private_staging: bool = True

    # ---- QA Memory (UC8). Empty EMBEDDING_MODEL: a local word vector, so no failure text leaves the server ----
    embedding_model: str = ""            # for example gemini/text-embedding-004, called through LiteLLM
    embedding_dim: int = 256
    memory_top_k: int = 5
    memory_min_similarity: float = 0.35

    # ---- Trends (UC11, TBD17) ----
    trend_min_pull_requests: int = 3

    @field_validator("secret_key", "webhook_secret")
    @classmethod
    def long_enough(cls, value: str) -> str:
        """An empty key would let anyone forge a session cookie or a webhook delivery, so the server refuses to start."""
        if len(value.strip()) < 16:
            raise ValueError("must be a long random string. See .env.example for how to generate one")
        return value

    @field_validator("public_url")
    @classmethod
    def no_trailing_slash(cls, url: str) -> str:
        return url.rstrip("/")  # callback and webhook addresses are built by adding a path to it

    @field_validator("database_url")
    @classmethod
    def use_psycopg(cls, url: str) -> str:
        """Neon hands out postgresql:// addresses, which SQLAlchemy reads as psycopg2. We install psycopg 3,
        so the same address the agents use works here unchanged."""
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url


settings = Settings()
