"""Calculators (spec section 10, FR-ST-05): contribution allocator, trim and rebalance.

Pure Decimal arithmetic on a snapshot of the holdings. Every order is in whole units (owner
decision Q8); money that whole units cannot use is reported as a remainder, so for the
allocator the orders plus the remainder always equal the new cash exactly. Fees are not
modelled here: the orders become draft transactions, where the broker's fee is filled in.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from decimal import ROUND_FLOOR, Decimal, localcontext
from typing import Literal

from folio.display import two

ZERO = Decimal(0)
ONE = Decimal(1)


@dataclass(frozen=True)
class Holding:
    account_id: int
    instrument_id: int
    name: str
    sleeve: str | None
    quantity: Decimal
    price_eur: Decimal | None  # latest close in euro
    price: Decimal | None  # latest close in the trading currency (what an order is placed at)
    currency: str | None

    @property
    def value_eur(self) -> Decimal:
        return ZERO if self.price_eur is None else self.quantity * self.price_eur


@dataclass(frozen=True)
class Candidate:
    """An instrument a sleeve can buy, even one not held yet (a listed member)."""

    instrument_id: int
    name: str
    price_eur: Decimal
    price: Decimal
    currency: str | None


@dataclass(frozen=True)
class SleeveTarget:
    id: str
    target: Decimal  # fraction of the portfolio
    band: Decimal | None = None  # the band that counts as "inside", as a fraction
    trim_threshold: Decimal | None = None  # fraction
    candidates: tuple[Candidate, ...] = ()  # what to buy, in order of preference


@dataclass(frozen=True)
class Order:
    side: Literal["buy", "sell"]
    sleeve: str
    instrument_id: int
    name: str
    quantity: Decimal
    price_eur: Decimal
    price: Decimal
    currency: str | None
    account_id: int | None = None  # for a sale: the account that holds the units

    @property
    def amount_eur(self) -> Decimal:
        return self.quantity * self.price_eur


@dataclass(frozen=True)
class Plan:
    orders: list[Order]
    remainder_eur: Decimal  # new cash left unspent (allocator) or net cash freed (trim, rebalance)
    notes: list[str] = field(default_factory=list)


def _floor_units(amount: Decimal, price: Decimal) -> Decimal:
    if price <= 0 or amount <= 0:
        return ZERO
    return (amount / price).to_integral_value(rounding=ROUND_FLOOR)


def sleeve_values(holdings: Sequence[Holding]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for h in holdings:
        if h.sleeve is not None:
            out[h.sleeve] = out.get(h.sleeve, ZERO) + h.value_eur
    return out


def total_value(holdings: Sequence[Holding]) -> Decimal:
    return sum((h.value_eur for h in holdings), ZERO)


def _buy_candidate(sleeve: SleeveTarget, holdings: Sequence[Holding]) -> Candidate | None:
    """The sleeve's listed members first; otherwise its smallest priced holding."""
    for c in sleeve.candidates:
        if c.price_eur > 0 and c.price > 0:
            return c
    held = [
        Candidate(h.instrument_id, h.name, h.price_eur, h.price, h.currency)
        for h in sorted(holdings, key=lambda x: (x.value_eur, x.instrument_id))
        if h.sleeve == sleeve.id and h.price_eur and h.price
    ]
    return held[0] if held else None


# --- contribution allocator ---------------------------------------------------------------------


def allocate_contribution(
    holdings: Sequence[Holding],
    sleeves: Sequence[SleeveTarget],
    cash: Decimal,
    min_order_eur: Decimal = Decimal(100),
) -> Plan:
    """Split new cash over the sleeves: shortfalls against `w_i x (T + C)` first, in proportion
    to their size; anything beyond the shortfalls follows the target weights. Orders below the
    minimum are merged into the next-largest one."""
    notes: list[str] = []
    targeted = [s for s in sleeves if s.target > 0]
    if cash <= 0 or not targeted:
        why = "Nothing to allocate." if cash <= 0 else "No sleeve has a target yet."
        return Plan([], max(cash, ZERO), [why])
    with localcontext() as ctx:
        ctx.prec = 40
        total = total_value(holdings)
        values = sleeve_values(holdings)
        shortfall = {
            s.id: max(ZERO, s.target * (total + cash) - values.get(s.id, ZERO)) for s in targeted
        }
        gap = sum(shortfall.values(), ZERO)
        if gap >= cash:
            amounts = {k: cash * v / gap for k, v in shortfall.items()} if gap else {}
        else:
            weights = sum((s.target for s in targeted), ZERO)
            amounts = {s.id: shortfall[s.id] + (cash - gap) * s.target / weights for s in targeted}

        # merge small orders into the next-largest one
        ordered = sorted(amounts.items(), key=lambda kv: (kv[1], kv[0]))
        for i in range(len(ordered) - 1):
            key, amount = ordered[i]
            if 0 < amount < min_order_eur:
                nxt_key, nxt = ordered[i + 1]
                ordered[i + 1] = (nxt_key, nxt + amount)
                ordered[i] = (key, ZERO)
                notes.append(
                    f"{key}: below the {two(min_order_eur)} EUR minimum, added to {nxt_key}."
                )
        amounts = dict(ordered)

        orders: list[Order] = []
        for s in targeted:
            amount = amounts.get(s.id, ZERO)
            if amount <= 0:
                continue
            candidate = _buy_candidate(s, holdings)
            if candidate is None:
                notes.append(f"{s.id}: no priced instrument to buy; its share stays unspent.")
                continue
            units = _floor_units(amount, candidate.price_eur)
            if units > 0:
                orders.append(_buy(s.id, candidate, units))
        spent = sum((o.amount_eur for o in orders), ZERO)
        remainder = cash - spent
        # whole units leave change: spend it on one more unit where the shortfall is largest,
        # starting an order there if the sleeve's share was too small for a single unit
        for s in sorted(targeted, key=lambda s: (-shortfall[s.id], s.id)):
            index = next((n for n, o in enumerate(orders) if o.sleeve == s.id), None)
            if index is not None:
                order = orders[index]
                if remainder >= order.price_eur:
                    orders[index] = replace(order, quantity=order.quantity + ONE)
                    remainder -= order.price_eur
                continue
            candidate = _buy_candidate(s, holdings)
            if candidate is not None and remainder >= candidate.price_eur:
                orders.append(_buy(s.id, candidate, ONE))
                remainder -= candidate.price_eur
    return Plan(orders, remainder, notes)


def _buy(sleeve: str, c: Candidate, units: Decimal) -> Order:
    return Order("buy", sleeve, c.instrument_id, c.name, units, c.price_eur, c.price, c.currency)


# --- trim ---------------------------------------------------------------------------------------


def trim(
    holdings: Sequence[Holding], sleeves: Sequence[SleeveTarget], sleeve_id: str | None = None
) -> Plan:
    """Sell only the excess above target for each breached sleeve (above its trim threshold,
    or outside its band on the heavy side). Never sells below the target: units are rounded
    down. Sells from the largest holding of the sleeve first."""
    total = total_value(holdings)
    values = sleeve_values(holdings)
    orders: list[Order] = []
    notes: list[str] = []
    if total == 0:
        return Plan([], ZERO, ["Nothing is valued yet."])
    with localcontext() as ctx:
        ctx.prec = 40
        for s in sleeves:
            if sleeve_id is not None and s.id != sleeve_id:
                continue
            weight = values.get(s.id, ZERO) / total
            limit = s.trim_threshold if s.trim_threshold is not None else (
                None if s.band is None else s.target + s.band
            )  # fmt: skip
            breached = limit is not None and weight > limit
            if not breached and sleeve_id is None:
                continue
            excess = values.get(s.id, ZERO) - s.target * total
            if excess <= 0:
                notes.append(f"{s.id} is not above its target; nothing to trim.")
                continue
            orders += _sell_down(s.id, excess, holdings)
    freed = sum((o.amount_eur for o in orders), ZERO)
    return Plan(orders, freed, notes)


def _sell_down(sleeve: str, excess: Decimal, holdings: Sequence[Holding]) -> list[Order]:
    orders = []
    held = sorted(
        (h for h in holdings if h.sleeve == sleeve and h.quantity > 0),
        key=lambda h: (-h.value_eur, h.instrument_id, h.account_id),
    )
    for h in held:
        if excess <= 0:
            break
        if not h.price_eur or not h.price:
            continue
        units = min(h.quantity, _floor_units(excess, h.price_eur))
        if units <= 0:
            continue
        orders.append(Order("sell", sleeve, h.instrument_id, h.name, units, h.price_eur, h.price,
                            h.currency, h.account_id))  # fmt: skip
        excess -= units * h.price_eur
    return orders


# --- rebalance ----------------------------------------------------------------------------------


def weights_after(holdings: Sequence[Holding], orders: Sequence[Order]) -> dict[str, Decimal]:
    """Sleeve weights once the orders are done (new cash that stays unspent is not invested,
    so it does not count)."""
    values = sleeve_values(holdings)
    for o in orders:
        signed = o.amount_eur if o.side == "buy" else -o.amount_eur
        values[o.sleeve] = values.get(o.sleeve, ZERO) + signed
    total = sum(values.values(), ZERO) + sum(
        (h.value_eur for h in holdings if h.sleeve is None), ZERO
    )
    with localcontext() as ctx:
        ctx.prec = 40
        return {k: ZERO if total == 0 else v / total for k, v in values.items()}


def rebalance(
    holdings: Sequence[Holding],
    sleeves: Sequence[SleeveTarget],
    cash: Decimal = ZERO,
    prefer_buys: bool = True,
) -> Plan:
    """Bring every sleeve with a band back inside it with as few trades as possible: only
    sleeves outside their band trade, one instrument each. With `prefer_buys`, new cash goes to
    the underweight sleeves first and a sale happens only for a sleeve that is still too heavy.

    Everything is measured against the whole: the holdings plus the new cash, which does not
    change when units are sold for cash or cash is spent on units."""
    banded = [s for s in sleeves if s.band is not None]
    if not banded:
        return Plan([], cash, ["No sleeve has a target and a band yet."])
    notes: list[str] = []
    orders: list[Order] = []
    whole = total_value(holdings) + max(cash, ZERO)
    available = max(cash, ZERO)
    if whole == 0:
        return Plan([], available, ["Nothing is valued yet."])

    def value(sleeve: SleeveTarget) -> Decimal:
        v = sleeve_values(holdings).get(sleeve.id, ZERO)
        for o in orders:
            if o.sleeve == sleeve.id:
                v += o.amount_eur if o.side == "buy" else -o.amount_eur
        return v

    def gap(sleeve: SleeveTarget) -> Decimal:
        with localcontext() as ctx:
            ctx.prec = 40
            return value(sleeve) / whole - sleeve.target

    def buy_underweights() -> None:
        nonlocal available
        under = [s for s in banded if gap(s) < -(s.band or ZERO)]
        needs = {s.id: max(ZERO, s.target * whole - value(s)) for s in under}
        need = sum(needs.values(), ZERO)
        for s in under:
            if available <= 0 or need == 0:
                break
            with localcontext() as ctx:
                ctx.prec = 40
                share = min(needs[s.id], available * needs[s.id] / need)
            candidate = _buy_candidate(s, holdings)
            if candidate is None:
                notes.append(f"{s.id}: no priced instrument to buy.")
                continue
            units = _floor_units(share, candidate.price_eur)
            if units > 0:
                order = _buy(s.id, candidate, units)
                orders.append(order)
                available -= order.amount_eur

    if prefer_buys and available > 0:
        buy_underweights()
    for s in banded:  # sell what is still too heavy, down to target and never below
        if gap(s) > (s.band or ZERO):
            sells = _sell_down(s.id, value(s) - s.target * whole, holdings)
            orders += sells
            available += sum((o.amount_eur for o in sells), ZERO)
    buy_underweights()  # and buy what is still too light, with what is available now
    if not orders:
        notes.append("Every sleeve is inside its band; nothing to do.")
    return Plan(orders, available, notes)
