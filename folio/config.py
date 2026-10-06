from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_prefix="FOLIO_", env_file=".env", extra="ignore")

    secret_key: str = Field(default="", description="Encrypts stored secrets and signs sessions")
    db_url: str = "sqlite:////data/folio.db"
    base_url: str | None = None
    tz: str = "Europe/Amsterdam"
    log_level: str = "INFO"
    backup_dir: str = "/data/backups"
    extra_backup_dir: str | None = None
    version: str | None = None  # the build, e.g. the git commit; set by the image (FR-SY-10)
    # Optional sign-in by Tailscale Serve's identity headers (FR-SY-04). Off unless BOTH are set:
    # the tailnet login that may sign in, and the addresses Tailscale Serve connects from.
    tailscale_user: str | None = None
    trusted_proxies: str = ""  # comma separated addresses or ranges, e.g. 172.18.0.1,10.0.0.0/8

    def require_secret_key(self) -> str:
        if len(self.secret_key) < 32:
            raise RuntimeError(
                "FOLIO_SECRET_KEY is missing or too short (need 32+ characters). "
                "Run `folio init` to generate one."
            )
        return self.secret_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
