"""Running the calculators on the real holdings, and turning their orders into draft
transactions the owner confirms on Insights (FR-ST-05)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio import analytics_service as svc
from folio.audit import write_audit
from folio.db.models import Account
from folio.db.models_ledger import Instrument, LedgerTransaction
from folio.instruments import primary_listing
from folio.ledger_service import (
    TransactionError,
    TransactionIn,
    insert_transaction,
    normalize,
    preview_sell_transaction,
)
from folio.marketdata.prices import PriceService
from folio.positions import load_positions
from folio.strategies.calculators import (
    Candidate,
    Holding,
    Plan,
    SleeveTarget,
    allocate_contribution,
    rebalance,
    trim,
    weights_after,
)
from folio.strategies.inputs import sleeve_of_instruments
from folio.strategies.schema import StrategyDef, is_isin

ZERO = Decimal(0)
HUNDRED = Decimal(100)
Kind = Literal["allocator", "trim", "rebalance"]


@dataclass(frozen=True)
class Result:
    plan: Plan
    before: dict[str, Decimal]
    after: dict[str, Decimal]
    realized: dict[int, Decimal]  # order index -> realized result of a sale


def holdings_for(db: Session, strategy: StrategyDef, today: date) -> list[Holding]:
    mapping = sleeve_of_instruments(db, strategy)
    rows, _ = load_positions(db, today=today)
    out = []
    for r in rows:
        value = None if r.metrics is None else r.metrics.market_value_eur
        quantity = r.state.quantity
        price_eur = None if value is None or quantity == 0 else value / quantity
        out.append(
            Holding(
                account_id=r.account.id,
                instrument_id=r.instrument.id,
                name=r.instrument.name,
                sleeve=mapping.get(r.instrument.id),
                quantity=quantity,
                price_eur=price_eur,
                price=None if r.price is None else r.price.close,
                currency=None if r.listing is None else r.listing.currency,
            )
        )
    return out


def targets_for(db: Session, strategy: StrategyDef, today: date) -> list[SleeveTarget]:
    """Sleeves with a target, with the instruments each can buy: its listed members (ISINs),
    priced in euro and in their trading currency."""
    members: dict[str, list[Instrument]] = {}
    isins = {m for s in strategy.sleeves for m in s.members if is_isin(m)}
    by_isin = {
        i.isin: i
        for i in db.scalars(
            select(Instrument).where(Instrument.isin.in_(isins), Instrument.deleted_at.is_(None))
        )
    }
    for s in strategy.sleeves:
        members[s.id] = [by_isin[m] for m in s.members if m in by_isin]
    extras = [i.id for found in members.values() for i in found]
    ctx = svc.get_context(db, today, extra_instrument_ids=extras)
    prices = PriceService(db)
    out = []
    for s in strategy.sleeves:
        if s.target_pct is None:
            continue
        candidates = []
        for instrument in members[s.id]:
            series = ctx.prices.get(instrument.id) or []
            price_eur = next((p for p in reversed(series) if p is not None), None)
            listing = primary_listing(db, instrument.id)
            bar = None if listing is None else prices.last_bar(listing.id, today)
            if price_eur is None or bar is None or listing is None:
                continue
            candidates.append(
                Candidate(instrument.id, instrument.name, price_eur, bar.close, listing.currency)
            )
        band = s.soft_band_pp if s.soft_band_pp is not None else s.hard_band_pp
        out.append(
            SleeveTarget(
                id=s.id,
                target=s.target_pct / HUNDRED,
                band=None if band is None else band / HUNDRED,
                trim_threshold=None
                if s.trim_threshold_pct is None
                else s.trim_threshold_pct / HUNDRED,
                candidates=tuple(candidates),
            )
        )
    return out


def calculate(
    db: Session,
    strategy: StrategyDef,
    kind: Kind,
    today: date,
    amount_eur: Decimal | None = None,
    sleeve: str | None = None,
) -> Result:
    holdings = holdings_for(db, strategy, today)
    sleeves = targets_for(db, strategy, today)
    plan_settings = strategy.contribution_plan
    if kind == "allocator":
        cash = amount_eur if amount_eur is not None else (
            plan_settings.amount_eur if plan_settings and plan_settings.amount_eur else ZERO
        )  # fmt: skip
        minimum = plan_settings.min_order_eur if plan_settings else Decimal(100)
        plan = allocate_contribution(holdings, sleeves, cash, minimum)
    elif kind == "trim":
        plan = trim(holdings, sleeves, sleeve)
    else:
        plan = rebalance(holdings, sleeves, amount_eur or ZERO, strategy.prefer_buys)
    realized: dict[int, Decimal] = {}
    for n, order in enumerate(plan.orders):
        if order.side != "sell" or order.account_id is None:
            continue
        try:
            preview = preview_sell_transaction(
                db,
                TransactionIn(
                    account_id=order.account_id,
                    type="sell",
                    trade_date=today,
                    instrument_id=order.instrument_id,
                    quantity=order.quantity,
                    price=order.price,
                ),  # fmt: skip
            )
        except TransactionError:
            continue
        realized[n] = preview.realized_pnl_eur
    before = weights_after(holdings, [])
    return Result(plan, before, weights_after(holdings, plan.orders), realized)


@dataclass(frozen=True)
class DraftOrder:
    side: Literal["buy", "sell"]
    instrument_id: int
    quantity: Decimal
    price: Decimal
    account_id: int | None = None


def to_drafts(
    db: Session, orders: list[DraftOrder], today: date, note: str | None = None
) -> list[LedgerTransaction]:
    """Draft transactions for the orders: nothing changes until each is confirmed. A buy without
    an account goes to the first active account."""
    default = db.scalars(
        select(Account)
        .where(Account.deleted_at.is_(None), Account.active.is_(True))
        .order_by(Account.id)
    ).first()
    created = []
    for order in orders:
        account_id = order.account_id or (None if default is None else default.id)
        if account_id is None:
            raise TransactionError("Add an account first.")
        fields = normalize(
            db,
            TransactionIn(
                account_id=account_id,
                type=order.side,
                trade_date=today,
                instrument_id=order.instrument_id,
                quantity=order.quantity,
                price=order.price,
                note=note or "From a strategy calculator.",
            ),  # fmt: skip
            today,
        )
        row = insert_transaction(db, fields, source="strategy", status="draft")
        write_audit(db, "user", "transaction", "create", entity_id=row.id,
                    diff={"type": order.side, "status": "draft", "source": "strategy"})  # fmt: skip
        created.append(row)
    db.flush()
    return created
