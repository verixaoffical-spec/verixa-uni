from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    public_url: str = "http://localhost:8000"
    secret_key: str
    webhook_secret: str
    database_url: str = "postgresql+psycopg://verixa:verixa@localhost:5432/verixa"
    totp_encryption_key: str = ""  # a Fernet key for two-step verification secrets, see .env.example

    github_client_id: str
    github_client_secret: str
    atlassian_client_id: str
    atlassian_client_secret: str

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
