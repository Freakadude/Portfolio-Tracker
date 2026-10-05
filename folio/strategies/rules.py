"""The rules engine (spec section 10): deterministic checks of a strategy against the portfolio.

Pure functions only. `folio/strategies/inputs.py` gathers the numbers from the database; this
module decides what needs attention and says so in three registers: the full message for the
inbox (amounts allowed), a push text without euro amounts, and an anonymous push text without
names (FR-NT-07). Drift comes from `analytics.allocation.drift`, the same function the charts
use, so a signal never disagrees with a dashboard.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, localcontext

from folio.analytics.allocation import drift
from folio.analytics.risk import correlation, daily_returns
from folio.strategies.schema import (
    SEVERITIES,
    CashBufferRule,
    ConcentrationLimitRule,
    ContributionDueRule,
    CorrelationShiftRule,
    DrawdownRule,
    DriftBandRule,
    MacroThresholdRule,
    PriceLevelRule,
    PriceMoveRule,
    Rule,
    Severity,
    StaleDataRule,
    StrategyDef,
    ThesisReviewDueRule,
    TrimThresholdRule,
)

ZERO = Decimal(0)
HUNDRED = Decimal(100)
Series = Sequence[tuple[date, Decimal]]


@dataclass(frozen=True)
class SleeveState:
    weight: Decimal  # fraction of the valued portfolio
    value_eur: Decimal


@dataclass(frozen=True)
class PositionState:
    instrument_id: int
    name: str
    isin: str | None
    sleeve: str | None  # the strategy sleeve it belongs to
    weight: Decimal | None
    closes_eur: Series  # recent daily closes in euro, oldest first
    close: Decimal | None  # the latest close in the trading currency
    currency: str | None


@dataclass(frozen=True)
class RuleInputs:
    today: date
    total_eur: Decimal
    sleeves: dict[str, SleeveState]
    positions: list[PositionState]
    portfolio_index: Series  # time-weighted index, for the portfolio drawdown
    sleeve_returns: Mapping[str, Series]  # daily returns per strategy sleeve
    macro: Mapping[str, Series]  # strategy series code -> points, oldest first
    stale: list[str]  # names of held instruments whose price is out of date
    tracked_cash_eur: Decimal | None  # None when no account tracks cash (Q7)
    strategy_since: date  # when this version was saved, the anchor for review cycles


@dataclass(frozen=True)
class Finding:
    rule_id: str
    rule_type: str
    subject: str
    severity: Severity
    title: str  # inbox title; may hold amounts and names
    message: str  # inbox body
    push: str  # no euro amounts
    push_anonymous: str  # no euro amounts and no names
    value: Decimal | None = None  # what worsening is measured on
    variant: str = ""  # part of the dedup key: a soft and a hard breach are different events
    payload: dict[str, str] = field(default_factory=dict)

    @property
    def dedup_key(self) -> str:
        return ":".join(p for p in (self.rule_id, self.subject, self.variant) if p)


@dataclass(frozen=True)
class RuleStatus:
    rule_id: str
    rule_type: str
    ready: bool
    reason: str | None  # why it cannot fire yet


@dataclass(frozen=True)
class Evaluation:
    findings: list[Finding]
    statuses: list[RuleStatus]


def _pct(value: Decimal, places: int = 1) -> str:
    return f"{(value * HUNDRED).quantize(Decimal(1).scaleb(-places)):f}"


def _num(value: Decimal, places: int = 2) -> str:
    return f"{value.quantize(Decimal(1).scaleb(-places)):f}"


def _raise(severity: Severity, at_least: Severity) -> Severity:
    return max(severity, at_least, key=SEVERITIES.index)


def _applies(applies_to: object, name: str) -> bool:
    return applies_to == "all" or (isinstance(applies_to, list) and name in applies_to)


# --- one function per rule type -----------------------------------------------------------------


def _drift_band(rule: DriftBandRule, s: StrategyDef, x: RuleInputs) -> list[Finding]:
    out = []
    for spec in s.sleeves:
        if not _applies(rule.applies_to, spec.id) or spec.target_pct is None:
            continue
        state = x.sleeves.get(spec.id, SleeveState(ZERO, ZERO))
        d = drift(state.weight, spec.target_pct / HUNDRED)
        if d is None:
            continue
        gap = abs(d.pp) * HUNDRED  # percentage points
        hard = spec.hard_band_pp is not None and gap > spec.hard_band_pp
        soft = spec.soft_band_pp is not None and gap > spec.soft_band_pp
        if not (hard or soft):
            continue
        side = "over" if d.pp > 0 else "under"
        advice = (
            "Consider a trade back inside the band."
            if hard
            else "Direct new money to bring it back."
            if side == "under"
            else "Direct new money elsewhere to bring it back."
        )
        band = spec.hard_band_pp if hard else spec.soft_band_pp
        kind = "hard" if hard else "soft"
        title = f"{spec.id} is {_num(gap, 1)} pp {side} its target ({kind} band {band} pp)"
        out.append(
            Finding(
                rule.id,
                rule.type,
                spec.id,
                _raise(rule.severity, "high") if hard else rule.severity,
                title,
                f"{spec.id} weighs {_pct(d.actual)}% against a target of "
                f"{_pct(d.target)}%. {advice}",
                f"{title}. {advice}",
                f"A sleeve is outside its {'hard' if hard else 'soft'} band. {advice}",
                value=gap,
                variant="hard" if hard else "soft",
                payload={"weight": str(d.actual), "target": str(d.target), "drift_pp": str(gap)},
            )
        )
    return out


def _trim_threshold(rule: TrimThresholdRule, s: StrategyDef, x: RuleInputs) -> list[Finding]:
    out = []
    for spec in s.sleeves:
        if not _applies(rule.applies_to, spec.id) or spec.trim_threshold_pct is None:
            continue
        state = x.sleeves.get(spec.id, SleeveState(ZERO, ZERO))
        weight = state.weight * HUNDRED
        if weight <= spec.trim_threshold_pct:
            continue
        title = f"{spec.id} is above its trim threshold of {spec.trim_threshold_pct}%"
        out.append(
            Finding(
                rule.id,
                rule.type,
                spec.id,
                rule.severity,
                title,
                f"{spec.id} weighs {_num(weight, 1)}%, above the trim level of "
                f"{spec.trim_threshold_pct}% you set in advance. The trim calculator shows the "
                "sale back to target and its realized result.",
                f"{title}. Open the trim calculator.",
                "A sleeve is above its trim threshold. Open the trim calculator.",
                value=weight,
                payload={"weight_pct": str(weight), "threshold_pct": str(spec.trim_threshold_pct)},
            )
        )
    return out


def _price_drawdown(closes: Series) -> Decimal | None:
    if not closes:
        return None
    peak = max(c for _, c in closes)
    last = closes[-1][1]
    return None if peak == 0 else (peak - last) / peak


def _drawdown(rule: DrawdownRule, _s: StrategyDef, x: RuleInputs) -> list[Finding]:
    limit = rule.threshold_pct / HUNDRED
    out = []
    if rule.scope == "portfolio":
        fall = _price_drawdown(x.portfolio_index)
        if fall is not None and fall >= limit:
            title = f"The portfolio is {_pct(fall)}% below its peak"
            out.append(
                Finding(
                    rule.id,
                    rule.type,
                    "portfolio",
                    rule.severity,
                    title,
                    f"{title}. Time to reread your principles, not a signal to sell.",
                    f"{title}. Review, not a sell signal.",
                    f"{title}. Review, not a sell signal.",
                    value=fall * HUNDRED,
                )  # fmt: skip
            )
        return out
    for p in x.positions:
        fall = _price_drawdown(p.closes_eur)
        if fall is None or fall < limit:
            continue
        title = f"{p.name} is {_pct(fall)}% below its peak"
        out.append(
            Finding(
                rule.id,
                rule.type,
                p.name,
                rule.severity,
                title,
                f"{title} of the last year. Review its thesis: does the reason you hold it still "
                "stand? A drawdown alone is not a reason to sell.",
                f"{title}. Review the thesis.",
                f"A position is {_pct(fall)}% below its peak. Review the thesis.",
                value=fall * HUNDRED,
                payload={"instrument_id": str(p.instrument_id)},
            )
        )
    return out


def _price_move(rule: PriceMoveRule, _s: StrategyDef, x: RuleInputs) -> list[Finding]:
    out = []
    for p in x.positions:
        if not _applies(rule.applies_to, p.sleeve or ""):
            continue
        returns = daily_returns(list(p.closes_eur))
        if not returns:
            continue
        day, move = returns[-1]
        if day < x.today - timedelta(days=4):
            continue  # not a move of today
        size = abs(move)
        hit = rule.pct is not None and size * HUNDRED >= rule.pct
        if not hit and rule.sigma is not None:
            history = [r for _, r in returns[-rule.window_days - 1 : -1]]
            if len(history) >= 10:
                with localcontext() as c:
                    c.prec = 40
                    mean = sum(history, ZERO) / len(history)
                    var = sum(((r - mean) ** 2 for r in history), ZERO) / (len(history) - 1)
                    sd = var.sqrt()
                hit = sd > 0 and size >= rule.sigma * sd
        if not hit:
            continue
        direction = "up" if move > 0 else "down"
        title = f"{p.name} moved {direction} {_pct(size)}% on {day.isoformat()}"
        out.append(
            Finding(
                rule.id,
                rule.type,
                p.name,
                rule.severity,
                title,
                f"{title}. An unusual move; check the news for a cause.",
                f"{title}.",
                f"A position moved {direction} {_pct(size)}% in a day.",
                value=size * HUNDRED,
                variant=day.isoformat(),
                payload={"instrument_id": str(p.instrument_id)},
            )  # fmt: skip
        )
    return out


def level_crossed(close: Decimal, above: Decimal | None, below: Decimal | None) -> str | None:
    if above is not None and close > above:
        return "above"
    if below is not None and close < below:
        return "below"
    return None


def _price_level(rule: PriceLevelRule, _s: StrategyDef, x: RuleInputs) -> list[Finding]:
    p = next((p for p in x.positions if p.isin == rule.instrument), None)
    if p is None or p.close is None:
        return []
    side = level_crossed(p.close, rule.above, rule.below)
    if side is None:
        return []
    level = rule.above if side == "above" else rule.below
    title = f"{p.name} closed {side} {level} {p.currency or ''}".rstrip()
    return [
        Finding(
            rule.id,
            rule.type,
            p.name,
            rule.severity,
            title,
            f"{title}: {p.close}.",
            f"{p.name} closed {side} the level you set.",
            f"A position closed {side} a level you set.",
            variant=side,
            payload={"instrument_id": str(p.instrument_id)},
        )  # fmt: skip
    ]


def _value_at(series: Series, day: date) -> Decimal | None:
    found = None
    for d, v in series:
        if d > day:
            break
        found = v
    return found


def _macro_threshold(rule: MacroThresholdRule, s: StrategyDef, x: RuleInputs) -> list[Finding]:
    points = x.macro.get(rule.series) or []
    if not points:
        return []
    last_day, last = points[-1]
    reasons: list[tuple[str, Decimal, str]] = []  # (text, value, variant)
    if rule.above is not None and last > rule.above:
        reasons.append((f"is {last}, above {rule.above}", last, "above"))
    if rule.below is not None and last < rule.below:
        reasons.append((f"is {last}, below {rule.below}", last, "below"))
    before = _value_at(points, last_day - timedelta(days=rule.window_days))
    if before is not None:
        if rule.change_bp is not None:
            bp = (last - before) * HUNDRED
            if abs(bp) >= rule.change_bp:
                reasons.append(
                    (f"moved {_num(bp, 0)} bp in {rule.window_days} days", abs(bp), "change")
                )
        if rule.change_pct is not None and before != 0:
            pct = (last - before) / before * HUNDRED
            if abs(pct) >= rule.change_pct:
                reasons.append(
                    (f"moved {_num(pct, 1)}% in {rule.window_days} days", abs(pct), "change")
                )
    sleeves = ", ".join(rule.applies_to)
    out = []
    for text, value, variant in reasons:
        title = f"{rule.series} {text}"
        concern = f" It concerns {sleeves}." if sleeves else ""
        out.append(
            Finding(
                rule.id,
                rule.type,
                rule.series,
                rule.severity,
                title,
                f"{title} (latest {last_day.isoformat()}).{concern}",
                f"{title}.{concern}",
                f"A macro indicator you watch {text.split(',')[0]}.",
                value=value,
                variant=variant,
                payload={"series": rule.series},
            )  # fmt: skip
        )
    return out


def _correlation_shift(rule: CorrelationShiftRule, _s: StrategyDef, x: RuleInputs) -> list[Finding]:
    hedge = x.sleeve_returns.get(rule.hedge) or []
    start = x.today - timedelta(days=rule.window_days)
    hedge = [(d, r) for d, r in hedge if d > start]
    out = []
    for other in rule.against:
        returns = [(d, r) for d, r in x.sleeve_returns.get(other) or [] if d > start]
        rho = correlation(hedge, returns)
        if rho is None or rho <= rule.above:
            continue
        title = f"{rule.hedge} now moves with {other} (correlation {_num(rho)})"
        out.append(
            Finding(
                rule.id,
                rule.type,
                f"{rule.hedge}/{other}",
                rule.severity,
                title,
                f"{title} over {rule.window_days} days, above {rule.above}. The hedge may "
                "not protect against a fall in that sleeve as you intended.",
                f"{title}.",
                "A hedge is moving with the sleeve it should protect.",
                value=rho,
            )  # fmt: skip
        )
    return out


def next_contribution(plan_date: date | None, cadence: str | None, today: date) -> date | None:
    if plan_date is None:
        return None
    step = {"weekly": 7, "monthly": 30, "quarterly": 91}.get(cadence or "", 0)
    day = plan_date
    while step and day < today:
        if cadence == "monthly":
            day = date(day.year + day.month // 12, day.month % 12 + 1, min(day.day, 28))
        elif cadence == "quarterly":
            month = day.month + 3
            day = date(day.year + (month - 1) // 12, (month - 1) % 12 + 1, min(day.day, 28))
        else:
            day += timedelta(days=step)
    return day


def _contribution_due(rule: ContributionDueRule, s: StrategyDef, x: RuleInputs) -> list[Finding]:
    plan = s.contribution_plan
    if plan is None or plan.amount_eur is None:
        return []
    due = next_contribution(plan.next_date, plan.cadence, x.today)
    if due is None or (due - x.today).days > rule.days_before:
        return []
    title = f"Contribution of {plan.amount_eur} EUR due on {due.isoformat()}"
    return [
        Finding(
            rule.id,
            rule.type,
            "contribution",
            rule.severity,
            title,
            f"{title}. The allocator shows where the new money brings the sleeves closest "
            "to their targets.",
            f"A contribution is due on {due.isoformat()}.",
            f"A contribution is due on {due.isoformat()}.",
            variant=due.isoformat(),
        )  # fmt: skip
    ]


def _cash_buffer(rule: CashBufferRule, s: StrategyDef, x: RuleInputs) -> list[Finding]:
    cash, limits = x.tracked_cash_eur, s.risk_limits
    if cash is None:
        return []
    side = None
    if limits.min_cash_eur is not None and cash < limits.min_cash_eur:
        side, bound = "below", limits.min_cash_eur
    elif limits.max_cash_eur is not None and cash > limits.max_cash_eur:
        side, bound = "above", limits.max_cash_eur
    if side is None:
        return []
    title = f"Cash is {side} its range"
    return [
        Finding(
            rule.id,
            rule.type,
            "cash",
            rule.severity,
            title,
            f"Cash is {_num(cash)} EUR, {side} the {_num(bound)} EUR you set.",
            f"{title}.",
            f"{title}.",
            variant=side,
        )  # fmt: skip
    ]


def _thesis_review_due(rule: ThesisReviewDueRule, s: StrategyDef, x: RuleInputs) -> list[Finding]:
    out = []
    for t in s.theses:
        due = t.next_review
        if due is None and t.review_every_days is not None:
            due = x.strategy_since + timedelta(days=t.review_every_days)
            while due + timedelta(days=t.review_every_days) <= x.today:
                due += timedelta(days=t.review_every_days)
        if due is None or (due - x.today).days > rule.days_before:
            continue
        subject = t.sleeve or t.instrument or "thesis"
        title = f"Review the thesis for {subject}"
        why = f" You hold it because: {t.why}" if t.why else ""
        out.append(
            Finding(
                rule.id,
                rule.type,
                subject,
                rule.severity,
                title,
                f"{title} (due {due.isoformat()}).{why}",
                f"{title}.",
                "A thesis review is due.",
                variant=due.isoformat(),
            )  # fmt: skip
        )
    return out


def _stale_data(rule: StaleDataRule, _s: StrategyDef, x: RuleInputs) -> list[Finding]:
    if not x.stale:
        return []
    names = ", ".join(sorted(x.stale))
    count = len(x.stale)
    title = f"{count} price{'s are' if count != 1 else ' is'} out of date"
    return [
        Finding(
            rule.id,
            rule.type,
            "prices",
            rule.severity,
            title,
            f"No recent close for: {names}. Values and rules use the last known price.",
            f"{title}: {names}.",
            f"{title}.",
            value=Decimal(count),
        )  # fmt: skip
    ]


def _concentration(_rule: ConcentrationLimitRule, _s: StrategyDef, _x: RuleInputs) -> list[Finding]:
    return []  # needs the holdings inside each ETF (FR-MD-09, Phase 4)


_EVALUATORS: dict[str, Callable[..., list[Finding]]] = {
    "drift_band": _drift_band,
    "trim_threshold": _trim_threshold,
    "drawdown": _drawdown,
    "price_move": _price_move,
    "price_level": _price_level,
    "macro_threshold": _macro_threshold,
    "correlation_shift": _correlation_shift,
    "contribution_due": _contribution_due,
    "cash_buffer": _cash_buffer,
    "thesis_review_due": _thesis_review_due,
    "stale_data": _stale_data,
    "concentration_limit": _concentration,
}


def status(rule: Rule, s: StrategyDef, x: RuleInputs) -> RuleStatus:
    """Whether a rule can fire at all, and if not, what it is waiting for."""
    reason: str | None = None
    if not rule.enabled:
        reason = "Switched off."
    elif isinstance(rule, ConcentrationLimitRule):
        reason = "Needs the holdings inside your ETFs, which arrive in Phase 4."
    elif isinstance(rule, DriftBandRule):
        if not any(
            sp.target_pct is not None and (sp.soft_band_pp or sp.hard_band_pp) is not None
            for sp in s.sleeves
            if _applies(rule.applies_to, sp.id)
        ):
            reason = "No sleeve has a target and a band yet."
    elif isinstance(rule, TrimThresholdRule):
        if not any(
            sp.trim_threshold_pct is not None
            for sp in s.sleeves
            if _applies(rule.applies_to, sp.id)
        ):
            reason = "No sleeve has a trim threshold yet."
    elif isinstance(rule, ContributionDueRule):
        plan = s.contribution_plan
        if plan is None or plan.amount_eur is None or plan.next_date is None:
            reason = "No contribution plan with an amount and a date."
    elif isinstance(rule, CashBufferRule):
        if x.tracked_cash_eur is None:
            reason = "No account tracks cash."
        elif s.risk_limits.min_cash_eur is None and s.risk_limits.max_cash_eur is None:
            reason = "No cash range under risk_limits."
    elif isinstance(rule, MacroThresholdRule) and not x.macro.get(rule.series):
        reason = f"No data for {rule.series} yet."
    elif isinstance(rule, ThesisReviewDueRule) and not s.theses:
        reason = "No theses written yet."
    return RuleStatus(rule.id, rule.type, reason is None, reason)


def evaluate(strategy: StrategyDef, inputs: RuleInputs) -> Evaluation:
    findings: list[Finding] = []
    statuses: list[RuleStatus] = []
    for rule in strategy.rules:
        st = status(rule, strategy, inputs)
        statuses.append(st)
        if st.ready:
            findings += _EVALUATORS[rule.type](rule, strategy, inputs)
    return Evaluation(findings, statuses)
