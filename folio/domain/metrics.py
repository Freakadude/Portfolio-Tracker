"""Position and portfolio metrics in EUR (spec section 7), derived from a LedgerState."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from folio.domain.ledger import ZERO, LedgerState, PositionState, precise


@dataclass(frozen=True)
class Quote:
    """A close in the trading currency plus the EUR rate for that day, with the day before."""

    price: Decimal
    fx_rate: Decimal  # trading currency -> EUR
    prev_price: Decimal | None = None
    prev_fx_rate: Decimal | None = None


@dataclass(frozen=True)
class PositionMetrics:
    instrument_id: int
    quantity: Decimal
    avg_cost_eur: Decimal | None
    cost_basis_eur: Decimal
    market_value_eur: Decimal
    unrealized_pnl_eur: Decimal
    unrealized_pct: Decimal | None
    realized_pnl_eur: Decimal
    income_eur: Decimal
    total_return_eur: Decimal  # unrealized + realized + income
    total_return_pct: Decimal | None  # over everything ever invested in the position
    day_change_eur: Decimal | None
    day_change_pct: Decimal | None
    market_value_native: Decimal  # price move only, no currency effect
    cost_basis_native: Decimal  # gross price paid in the trading currency, fees excluded
    unrealized_pnl_native: Decimal


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return None if denominator == 0 else numerator / denominator


def position_metrics(pos: PositionState, quote: Quote) -> PositionMetrics:
    with precise():
        qty = pos.quantity
        cost = pos.cost_basis_eur
        value = qty * quote.price * quote.fx_rate
        unrealized = value - cost
        total_return = unrealized + pos.realized_pnl_eur + pos.income_eur
        day_change: Decimal | None = None
        day_pct: Decimal | None = None
        if quote.prev_price is not None and quote.prev_fx_rate is not None:
            before = qty * quote.prev_price * quote.prev_fx_rate
            day_change = value - before
            day_pct = _ratio(day_change, before)
        value_native = qty * quote.price
        return PositionMetrics(
            instrument_id=pos.instrument_id,
            quantity=qty,
            avg_cost_eur=pos.avg_cost_eur,
            cost_basis_eur=cost,
            market_value_eur=value,
            unrealized_pnl_eur=unrealized,
            unrealized_pct=_ratio(unrealized, cost),
            realized_pnl_eur=pos.realized_pnl_eur,
            income_eur=pos.income_eur,
            total_return_eur=total_return,
            total_return_pct=_ratio(total_return, pos.invested_eur),
            day_change_eur=day_change,
            day_change_pct=day_pct,
            market_value_native=value_native,
            cost_basis_native=pos.cost_basis_native,
            unrealized_pnl_native=value_native - pos.cost_basis_native,
        )


@dataclass(frozen=True)
class PortfolioMetrics:
    market_value_eur: Decimal
    net_contributions_eur: Decimal
    total_pnl_eur: Decimal  # value - net contributions + income - standalone fees - taxes
    total_pnl_pct: Decimal | None  # over net contributions
    income_eur: Decimal
    standalone_fees_eur: Decimal
    taxes_eur: Decimal
    day_change_eur: Decimal | None
    day_change_pct: Decimal | None


def portfolio_metrics(state: LedgerState, quotes: Mapping[int, Quote]) -> PortfolioMetrics:
    """Totals over every held position. A position without a quote counts at zero value."""
    with precise():
        value = ZERO
        day = ZERO
        before = ZERO
        day_known = True
        for instrument_id, pos in state.positions.items():
            if pos.quantity == 0:
                continue
            quote = quotes.get(instrument_id)
            if quote is None:
                day_known = False
                continue
            m = position_metrics(pos, quote)
            value += m.market_value_eur
            if m.day_change_eur is None:
                day_known = False
            else:
                day += m.day_change_eur
                before += m.market_value_eur - m.day_change_eur
        income = state.total_income_eur
        pnl = value - state.net_contributions_eur + income - state.standalone_fees_eur
        pnl -= state.taxes_eur
        return PortfolioMetrics(
            market_value_eur=value,
            net_contributions_eur=state.net_contributions_eur,
            total_pnl_eur=pnl,
            total_pnl_pct=_ratio(pnl, state.net_contributions_eur),
            income_eur=income,
            standalone_fees_eur=state.standalone_fees_eur,
            taxes_eur=state.taxes_eur,
            day_change_eur=day if day_known else None,
            day_change_pct=_ratio(day, before) if day_known else None,
        )


def round_cents(value: Decimal) -> Decimal:
    """Display rounding only (half-even); stored values are never rounded."""
    return value.quantize(Decimal("0.01"), ROUND_HALF_EVEN)
