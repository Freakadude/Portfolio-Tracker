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


class ModelPrice(BaseModel):
    """What one model costs, in US dollars per million tokens (check Anthropic's pricing page)."""

    model_config = ConfigDict(extra="forbid")
    input_usd: Decimal = Field(ge=0)
    output_usd: Decimal = Field(ge=0)
    cache_write_usd: Decimal = Field(ge=0)  # writing a prompt to the cache (5-minute entry)
    cache_read_usd: Decimal = Field(ge=0)


def _default_prices() -> dict[str, ModelPrice]:
    def price(inp: str, out: str) -> ModelPrice:
        i = Decimal(inp)
        return ModelPrice(
            input_usd=i, output_usd=Decimal(out), cache_write_usd=i * Decimal("1.25"),
            cache_read_usd=i / 10,
        )  # fmt: skip

    return {
        "claude-sonnet-5-5": price("3", "15"),
        "claude-opus-5-5": price("5", "25"),
        "claude-haiku-4-5-20251001": price("1", "5"),
    }


class AgentSettings(Section):
    SECRETS: ClassVar[tuple[str, ...]] = ("anthropic_api_key",)
    enabled: bool = True
    monthly_budget_eur: Decimal = Field(default=Decimal("5"), ge=0)  # owner decision Q6
    # News triage (linking and impact) draws on the same budget but may use at most this much
    # of it, so it can never leave the agent nothing
    news_share_eur: Decimal = Field(default=Decimal("1.50"), ge=0)
    daily_run_cap: int = Field(default=10, ge=0)
    per_run_token_cap: int = Field(default=60000, ge=1000)
    web_search_max_uses: int = Field(default=5, ge=0)
    web_search_domains: list[str] = Field(default_factory=list)
    privacy_mode: bool = True
    daily_review_time: str = "19:30"  # local time, weekdays
    models: dict[str, str] = Field(
        default_factory=lambda: {
            "daily_review": "claude-sonnet-5-5",
            "event_run": "claude-sonnet-5-5",
            "weekly_review": "claude-opus-5-5",
            "contribution_plan": "claude-sonnet-5-5",
            "on_demand": "claude-sonnet-5-5",
            "news_triage": "claude-haiku-4-5-20251001",
            "news_escalation": "claude-sonnet-5-5",
        }
    )
    prices: dict[str, ModelPrice] = Field(default_factory=_default_prices)
    web_search_usd_per_1000: Decimal = Field(default=Decimal("10"), ge=0)
    usd_per_eur_fallback: Decimal = Field(
        default=Decimal("1.10"), gt=0
    )  # when no ECB rate is stored
    anthropic_api_key: str | None = None

    @field_validator("daily_review_time")
    @classmethod
    def _time(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            raise ValueError("Use a time like 19:30.")
        if not (0 <= int(parts[0]) < 24 and 0 <= int(parts[1]) < 60):
            raise ValueError("Use a time like 19:30.")
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"


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


PushChannel = Literal["home_assistant", "ntfy"]
Route = Literal["critical", "high", "medium", "low", "info", "digest"]


def _default_routing() -> dict[Route, list[PushChannel]]:
    """Spec section 13: critical, high and medium reach the phone (medium batched hourly),
    low and info stay in the inbox and the digest; the digest itself is pushed."""
    both: list[PushChannel] = ["home_assistant", "ntfy"]
    return {
        "critical": list(both),
        "high": list(both),
        "medium": list(both),
        "low": [],
        "info": [],
        "digest": list(both),
    }


class NotificationsSettings(Section):
    SECRETS: ClassVar[tuple[str, ...]] = ("home_assistant_token", "ntfy_token")
    # the phone channel chosen in the setup wizard; "none" switches phone pushes off (Q5)
    channel: Literal["home_assistant", "ntfy", "web_push", "none"] = "home_assistant"
    # severity (and "digest") -> the channels that get a push; a channel that is not set up
    # is skipped (FR-NT-03)
    routing: dict[Route, list[PushChannel]] = Field(default_factory=_default_routing)
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "07:30"
    daily_push_cap: int = Field(default=5, ge=0)  # critical pushes do not count
    # lock-screen privacy: "amounts" leaves out euro amounts, "names" also instrument names
    push_privacy: Literal["amounts", "names"] = "amounts"
    digest_daily: bool = True
    digest_daily_time: str = "18:30"
    digest_weekly: bool = True  # Sundays, after the daily digest
    app_url: str | None = Field(default=None, max_length=300)  # where a tap on a push leads
    home_assistant_url: str | None = None
    home_assistant_service: str | None = None  # e.g. notify.mobile_app_<device>
    ntfy_url: str | None = None
    ntfy_topic: str | None = None
    home_assistant_token: str | None = None
    ntfy_token: str | None = None

    @field_validator("quiet_hours_start", "quiet_hours_end", "digest_daily_time")
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


class MacroSeriesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["fred", "ecb"]
    # FRED series id (DFII10), or an ECB dataflow/key (FM/D.U2.EUR.4F.KR.DFR.LEV); ECB_DFR is
    # the ECB deposit facility rate
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    unit: Literal["percent", "index", "level"] = "percent"


def _default_macro() -> list[MacroSeriesConfig]:
    return [
        MacroSeriesConfig(source="fred", code="DFII10", name="US 10-year real yield"),
        MacroSeriesConfig(
            source="fred", code="DTWEXBGS", name="Trade-weighted US dollar (broad)", unit="index"
        ),
        MacroSeriesConfig(source="fred", code="DFF", name="Fed funds rate"),
        MacroSeriesConfig(source="ecb", code="ECB_DFR", name="ECB deposit facility rate"),
    ]


class MacroSettings(Section):
    """The indicator series fetched every day (FR-MD-08). The active strategy's own
    `macro_series` are fetched as well."""

    series: list[MacroSeriesConfig] = Field(default_factory=_default_macro)


class HoldingsSource(BaseModel):
    """Where one ETF's holdings are refreshed from, besides an uploaded file."""

    model_config = ConfigDict(extra="forbid")
    url: str | None = Field(default=None, max_length=500)  # the issuer's CSV download
    eodhd: bool = False  # EODHD fundamentals (needs its Fundamentals plan)


class LookThroughSettings(Section):
    """ETF look-through (FR-MD-09). `sources` is keyed by instrument id."""

    sources: dict[str, HoldingsSource] = Field(default_factory=dict)
    stale_days: int = Field(default=45, ge=1)  # after this the snapshot is called out of date


class AnalyticsSettings(Section):
    """The risk-free rate for the Sharpe ratio (FR-PF-06): the ECB deposit facility rate, or a
    fixed percentage when the owner prefers one (or the ECB series is not yet loaded)."""

    risk_free_source: Literal["ecb_deposit", "fixed"] = "ecb_deposit"
    risk_free_fixed_pct: Decimal = Field(default=Decimal("2"), ge=0, le=25)


SECTIONS: dict[str, type[Section]] = {
    "general": GeneralSettings,
    "providers": ProvidersSettings,
    "agent": AgentSettings,
    "schedules": SchedulesSettings,
    "notifications": NotificationsSettings,
    "appearance": AppearanceSettings,
    "language": LanguageSettings,
    "retention": RetentionSettings,
    "analytics": AnalyticsSettings,
    "macro": MacroSettings,
    "lookthrough": LookThroughSettings,
}
