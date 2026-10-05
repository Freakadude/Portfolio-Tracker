"""The strategy document (spec section 10, appendix B): sleeves with targets and bands, risk
limits, typed rules, the owner's principles and position theses, and the contribution plan.

Everything that sets a target or a threshold is optional, so a strategy can be written down
before the numbers are decided (owner decision Q3); rules then skip what has no number.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Severity = Literal["info", "low", "medium", "high", "critical"]
SEVERITIES: tuple[Severity, ...] = ("info", "low", "medium", "high", "critical")
ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

Pct = Annotated[Decimal, Field(ge=0, le=100)]
Points = Annotated[Decimal, Field(ge=0, le=100)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SleeveSpec(_Model):
    id: str = Field(min_length=1, max_length=60)
    members: list[str] = Field(default_factory=list)  # ISINs, or tags of instruments
    tags: list[str] = Field(default_factory=list)  # tags of the sleeve itself, e.g. thematic
    target_pct: Pct | None = None
    soft_band_pp: Points | None = None
    hard_band_pp: Points | None = None
    trim_threshold_pct: Pct | None = None
    watch: list[str] = Field(default_factory=list)  # macro series codes

    @model_validator(mode="after")
    def _bands(self) -> SleeveSpec:
        soft, hard = self.soft_band_pp, self.hard_band_pp
        if soft is not None and hard is not None and hard < soft:
            raise ValueError("hard_band_pp must be at least soft_band_pp")
        return self


class MacroSeriesSpec(_Model):
    source: Literal["fred", "ecb"]
    code: str = Field(min_length=1, max_length=80)


class RiskLimits(_Model):
    max_single_company_lookthrough_pct: Pct | None = None
    max_thematic_total_pct: Pct | None = None
    min_cash_eur: Decimal | None = Field(default=None, ge=0)
    max_cash_eur: Decimal | None = Field(default=None, ge=0)


class Thesis(_Model):
    sleeve: str | None = None
    instrument: str | None = None  # an ISIN
    why: str | None = None
    invalidated_if: str | None = None
    indicators: list[str] = Field(default_factory=list)
    review_every_days: int | None = Field(default=None, ge=1)
    next_review: date | None = None


class ContributionPlan(_Model):
    amount_eur: Decimal | None = Field(default=None, gt=0)
    cadence: Literal["weekly", "monthly", "quarterly"] | None = None
    next_date: date | None = None
    min_order_eur: Decimal = Field(default=Decimal(100), ge=0)


# --- rules --------------------------------------------------------------------------------------


class _Rule(_Model):
    id: str = Field(min_length=1, max_length=60)
    severity: Severity = "medium"
    cooldown_days: int = Field(default=7, ge=0)
    # a condition that stays true fires again before the cooldown ends only once it has
    # worsened by this much (in the rule's own unit: percentage points, percent, ...)
    worsen_step: Decimal | None = Field(default=None, gt=0)
    enabled: bool = True


AppliesTo = Literal["all"] | list[str]


class DriftBandRule(_Rule):
    type: Literal["drift_band"]
    applies_to: AppliesTo = "all"


class TrimThresholdRule(_Rule):
    type: Literal["trim_threshold"]
    applies_to: AppliesTo = "all"


class ConcentrationLimitRule(_Rule):
    type: Literal["concentration_limit"]
    dimension: Literal["company", "country"] = "company"
    limit_pct: Pct | None = None  # default: the risk limit


class DrawdownRule(_Rule):
    type: Literal["drawdown"]
    scope: Literal["position", "portfolio"] = "position"
    threshold_pct: Pct


class PriceMoveRule(_Rule):
    type: Literal["price_move"]
    applies_to: AppliesTo = "all"
    pct: Decimal | None = Field(default=None, gt=0)
    sigma: Decimal | None = Field(default=None, gt=0)
    window_days: int = Field(default=60, ge=10)

    @model_validator(mode="after")
    def _one(self) -> PriceMoveRule:
        if self.pct is None and self.sigma is None:
            raise ValueError("give pct or sigma")
        return self


class PriceLevelRule(_Rule):
    type: Literal["price_level"]
    instrument: str  # an ISIN
    above: Decimal | None = Field(default=None, gt=0)
    below: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _one(self) -> PriceLevelRule:
        if self.above is None and self.below is None:
            raise ValueError("give above or below")
        return self


class MacroThresholdRule(_Rule):
    type: Literal["macro_threshold"]
    series: str
    above: Decimal | None = None
    below: Decimal | None = None
    change_bp: Decimal | None = Field(default=None, gt=0)  # for series in percent
    change_pct: Decimal | None = Field(default=None, gt=0)  # relative change of the level
    window_days: int = Field(default=30, ge=1)
    applies_to: list[str] = Field(default_factory=list)  # the sleeves it concerns

    @model_validator(mode="after")
    def _one(self) -> MacroThresholdRule:
        if all(v is None for v in (self.above, self.below, self.change_bp, self.change_pct)):
            raise ValueError("give above, below, change_bp or change_pct")
        return self


class CorrelationShiftRule(_Rule):
    type: Literal["correlation_shift"]
    hedge: str
    against: list[str] = Field(min_length=1)
    window_days: int = Field(default=90, ge=20)
    above: Decimal = Field(ge=-1, le=1)


class ContributionDueRule(_Rule):
    type: Literal["contribution_due"]
    days_before: int = Field(default=3, ge=0)


class CashBufferRule(_Rule):
    type: Literal["cash_buffer"]


class ThesisReviewDueRule(_Rule):
    type: Literal["thesis_review_due"]
    days_before: int = Field(default=0, ge=0)


class StaleDataRule(_Rule):
    type: Literal["stale_data"]


Rule = Annotated[
    DriftBandRule
    | TrimThresholdRule
    | ConcentrationLimitRule
    | DrawdownRule
    | PriceMoveRule
    | PriceLevelRule
    | MacroThresholdRule
    | CorrelationShiftRule
    | ContributionDueRule
    | CashBufferRule
    | ThesisReviewDueRule
    | StaleDataRule,
    Field(discriminator="type"),
]
RULE_TYPES = (
    "drift_band",
    "trim_threshold",
    "concentration_limit",
    "drawdown",
    "price_move",
    "price_level",
    "macro_threshold",
    "correlation_shift",
    "contribution_due",
    "cash_buffer",
    "thesis_review_due",
    "stale_data",
)


class StrategyDef(_Model):
    name: str = Field(min_length=1, max_length=100)
    base_currency: Literal["EUR"] = "EUR"
    principles: list[str] = Field(default_factory=list)
    prefer_buys: bool = True  # the rebalance calculator buys before it sells
    macro_series: dict[str, MacroSeriesSpec] = Field(default_factory=dict)
    sleeves: list[SleeveSpec] = Field(default_factory=list)
    risk_limits: RiskLimits = Field(default_factory=RiskLimits)
    rules: list[Rule] = Field(default_factory=list)
    theses: list[Thesis] = Field(default_factory=list)
    contribution_plan: ContributionPlan | None = None

    @model_validator(mode="after")
    def _references(self) -> StrategyDef:
        sleeves = [s.id for s in self.sleeves]
        _unique(sleeves, "sleeve id")
        _unique([r.id for r in self.rules], "rule id")
        known = set(sleeves)

        def check(names: list[str], where: str) -> None:
            for name in names:
                if name not in known:
                    raise ValueError(f"{where} refers to sleeve {name!r}, which is not defined")

        for s in self.sleeves:
            for code in s.watch:
                if code not in self.macro_series:
                    raise ValueError(
                        f"sleeve {s.id!r} watches {code!r}, which is not under macro_series"
                    )
        for r in self.rules:
            if isinstance(r, DriftBandRule | TrimThresholdRule | PriceMoveRule) and isinstance(
                r.applies_to, list
            ):
                check(r.applies_to, f"rule {r.id!r}")
            if isinstance(r, MacroThresholdRule):
                check(r.applies_to, f"rule {r.id!r}")
                if r.series not in self.macro_series:
                    raise ValueError(
                        f"rule {r.id!r} uses series {r.series!r}, which is not under macro_series"
                    )
            if isinstance(r, CorrelationShiftRule):
                check([r.hedge, *r.against], f"rule {r.id!r}")
        for t in self.theses:
            if t.sleeve is not None:
                check([t.sleeve], "a thesis")
        return self

    def sleeve(self, sleeve_id: str) -> SleeveSpec | None:
        return next((s for s in self.sleeves if s.id == sleeve_id), None)


class StrategyDocument(_Model):
    """The YAML file: everything sits under one `strategy:` key."""

    strategy: StrategyDef


def _unique(values: list[str], what: str) -> None:
    seen: set[str] = set()
    for v in values:
        if v in seen:
            raise ValueError(f"{what} {v!r} is used twice")
        seen.add(v)


def is_isin(value: str) -> bool:
    return bool(ISIN.match(value))
