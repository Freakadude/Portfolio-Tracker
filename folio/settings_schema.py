"""Typed settings sections (FR-SY-09). Secret fields are write-only: they are stored encrypted
through SecretStore, never in the setting table, and are shown masked."""

import re
from decimal import Decimal
from typing import ClassVar, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")
    SECRETS: ClassVar[tuple[str, ...]] = ()


class GeneralSettings(Section):
    timezone: str = "Europe/Amsterdam"
    number_format: Literal["eu", "us"] = "eu"  # eu: "€ 1.234,56"   us: "€1,234.56"

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise ValueError(f"Unknown timezone {v!r}. Use a name like Europe/Amsterdam.") from None
        return v


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    priority: int = Field(default=10, ge=1)
    daily_call_budget: int = Field(default=0, ge=0)  # 0 = provider default


def _default_providers() -> dict[str, ProviderConfig]:
    return {
        "eodhd": ProviderConfig(priority=1, daily_call_budget=20),  # used once a key is saved
        # Unofficial, but on by default (owner decision, ADR 0006): it is the only free source
        # with deep history for Xetra and Amsterdam listings.
        "yahoo": ProviderConfig(priority=2),
        "twelvedata": ProviderConfig(priority=3, daily_call_budget=800),  # needs a key
        "openfigi": ProviderConfig(priority=1),
        "ecb": ProviderConfig(priority=1),
        "fred": ProviderConfig(priority=1),
    }


class ProvidersSettings(Section):
    SECRETS: ClassVar[tuple[str, ...]] = (
        "eodhd_api_key",
        "twelvedata_api_key",
        "openfigi_api_key",
        "fred_api_key",
    )
    providers: dict[str, ProviderConfig] = Field(default_factory=_default_providers)
    eodhd_api_key: str | None = None
    twelvedata_api_key: str | None = None
    openfigi_api_key: str | None = None
    fred_api_key: str | None = None


class AgentSettings(Section):
    SECRETS: ClassVar[tuple[str, ...]] = ("anthropic_api_key",)
    enabled: bool = True
    monthly_budget_eur: Decimal = Field(default=Decimal("5"), ge=0)  # owner decision Q6
    daily_run_cap: int = Field(default=10, ge=0)
    per_run_token_cap: int = Field(default=60000, ge=1000)
    web_search_max_uses: int = Field(default=5, ge=0)
    web_search_domains: list[str] = Field(default_factory=list)
    privacy_mode: bool = True
    models: dict[str, str] = Field(
        default_factory=lambda: {
            "daily_review": "claude-sonnet-5-5",
            "event_run": "claude-sonnet-5-5",
            "weekly_review": "claude-opus-5-5",
            "contribution_plan": "claude-sonnet-5-5",
            "on_demand": "claude-sonnet-5-5",
            "news_triage": "claude-haiku-4-5-20251001",
        }
    )
    anthropic_api_key: str | None = None


class SchedulesSettings(Section):
    """Cron overrides per job name, e.g. {"nightly_eod": "30 19 * * 1-5"}."""

    cron_overrides: dict[str, str] = Field(default_factory=dict)

    @field_validator("cron_overrides")
    @classmethod
    def _cron(cls, v: dict[str, str]) -> dict[str, str]:
        for job, expr in v.items():
            if len(expr.split()) != 5:
                raise ValueError(f"Cron expression for {job!r} needs 5 fields, got {expr!r}.")
        return v


class NotificationsSettings(Section):
    SECRETS: ClassVar[tuple[str, ...]] = ("home_assistant_token", "ntfy_token")
    channel: Literal["home_assistant", "ntfy", "web_push", "none"] = "home_assistant"  # Q5
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "07:30"
    daily_push_cap: int = Field(default=5, ge=0)
    home_assistant_url: str | None = None
    home_assistant_service: str | None = None  # e.g. notify.mobile_app_<device>
    ntfy_url: str | None = None
    ntfy_topic: str | None = None
    home_assistant_token: str | None = None
    ntfy_token: str | None = None

    @field_validator("quiet_hours_start", "quiet_hours_end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("Use 24-hour HH:MM, for example 22:00.")
        return v


class AppearanceSettings(Section):
    theme: Literal["system", "light", "dark"] = "system"


class LanguageSettings(Section):
    language: Literal["en"] = "en"  # English only for now (Q10); the i18n layer allows more


class RetentionSettings(Section):
    quotes_days: int = Field(default=7, ge=1)
    agent_runs_days: int = Field(default=90, ge=1)
    news_days: int = Field(default=365, ge=1)


SECTIONS: dict[str, type[Section]] = {
    "general": GeneralSettings,
    "providers": ProvidersSettings,
    "agent": AgentSettings,
    "schedules": SchedulesSettings,
    "notifications": NotificationsSettings,
    "appearance": AppearanceSettings,
    "language": LanguageSettings,
    "retention": RetentionSettings,
}
