"""Allocator, trim and rebalance (FR-ST-05): exact sums, whole units, never below target."""

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from folio.strategies.calculators import (
    Candidate,
    Holding,
    SleeveTarget,
    allocate_contribution,
    rebalance,
    total_value,
    trim,
    weights_after,
)

D = Decimal


def holding(instrument: int, sleeve: str, units: int, price: str, account: int = 1) -> Holding:
    return Holding(
        account, instrument, f"I{instrument}", sleeve, D(units), D(price), D(price), "EUR"
    )


BOOK = [holding(1, "equity", 7, "100"), holding(2, "gold", 3, "100")]  # 700 / 300
SLEEVES = [
    SleeveTarget("equity", D("0.5"), D("0.05"), D("0.75")),
    SleeveTarget("gold", D("0.5"), D("0.05")),
]


def test_new_cash_goes_to_the_shortfall_first() -> None:
    plan = allocate_contribution(BOOK, SLEEVES, D(400))
    # T + C = 1400, so each sleeve should hold 700: equity is there, gold is 400 short
    assert [(o.sleeve, o.side, o.quantity) for o in plan.orders] == [("gold", "buy", D(4))]
    assert plan.remainder_eur == 0


def test_cash_beyond_the_shortfalls_follows_the_target_weights() -> None:
    plan = allocate_contribution(BOOK, SLEEVES, D(1000))
    # targets 1000 each: shortfalls equity 300, gold 700, exactly the cash
    assert {o.sleeve: o.quantity for o in plan.orders} == {"equity": D(3), "gold": D(7)}
    more = allocate_contribution(BOOK, SLEEVES, D(1200))
    # shortfalls 400 + 800... wait: targets 1100 each -> 400 and 800, exactly 1200
    assert sum((o.amount_eur for o in more.orders), D(0)) + more.remainder_eur == 1200


def test_small_orders_are_merged_into_the_next_largest() -> None:
    book = [holding(1, "equity", 50, "10"), holding(2, "gold", 49, "10")]  # 500 / 490
    plan = allocate_contribution(book, SLEEVES, D(1000), min_order_eur=D(100))
    # shortfalls: equity 495 - 500 < 0 -> 0? targets 995 each: equity 495, gold 505
    assert all(o.amount_eur >= 100 for o in plan.orders)
    tiny = allocate_contribution(book, SLEEVES, D(30), min_order_eur=D(100))
    # shortfalls equity 10, gold 20: the 10 is merged into gold
    assert [(o.sleeve, o.quantity) for o in tiny.orders] == [("gold", D(3))]
    assert any("added to gold" in n for n in tiny.notes)


def test_whole_units_leave_change_and_the_change_is_reported() -> None:
    book = [holding(1, "equity", 1, "333"), holding(2, "gold", 1, "333")]
    plan = allocate_contribution(book, SLEEVES, D(500))
    spent = sum((o.amount_eur for o in plan.orders), D(0))
    assert spent + plan.remainder_eur == 500 and plan.remainder_eur == 167
    assert all(o.quantity == o.quantity.to_integral_value() for o in plan.orders)


def test_a_sleeve_can_buy_a_member_it_does_not_hold_yet() -> None:
    sleeves = [
        *SLEEVES,
        SleeveTarget(
            "bonds", D("0.2"), candidates=(Candidate(9, "Bond ETF", D(50), D(50), "EUR"),)
        ),
    ]
    plan = allocate_contribution(BOOK, sleeves, D(500))
    assert any(o.instrument_id == 9 for o in plan.orders)


def test_without_targets_or_cash_there_is_nothing_to_allocate() -> None:
    assert allocate_contribution(BOOK, [SleeveTarget("x", D(0))], D(100)).remainder_eur == 100
    assert allocate_contribution(BOOK, SLEEVES, D(0)).orders == []


prices = st.decimals(min_value=D("0.5"), max_value=D("900"), places=2)


@settings(max_examples=150, deadline=None)
@given(
    st.lists(st.tuples(st.integers(0, 200), prices), min_size=2, max_size=5),
    st.lists(st.integers(1, 100), min_size=2, max_size=5),
    st.decimals(min_value=D("1"), max_value=D("50000"), places=2),
)
def test_the_allocator_always_adds_up_to_the_new_cash_exactly(
    positions: list[tuple[int, Decimal]], weights: list[int], cash: Decimal
) -> None:
    n = min(len(positions), len(weights))
    book = [holding(i, f"s{i}", units, price) for i, (units, price) in enumerate(positions[:n])]
    total_weight = sum(weights[:n])
    sleeves = [SleeveTarget(f"s{i}", D(w) / D(total_weight)) for i, w in enumerate(weights[:n])]
    plan = allocate_contribution(book, sleeves, cash)
    spent = sum((o.amount_eur for o in plan.orders), D(0))
    assert spent + plan.remainder_eur == cash  # exactly, not approximately
    assert plan.remainder_eur >= 0
    assert all(o.side == "buy" and o.quantity >= 1 for o in plan.orders)
    assert all(o.quantity == o.quantity.to_integral_value() for o in plan.orders)


def test_trim_sells_only_the_excess_and_never_below_target() -> None:
    book = [holding(1, "equity", 8, "100"), holding(2, "gold", 2, "100")]  # 80% equity
    plan = trim(book, SLEEVES)
    assert [(o.side, o.sleeve, o.quantity, o.account_id) for o in plan.orders] == [
        ("sell", "equity", D(3), 1)
    ]
    assert plan.remainder_eur == 300
    assert weights_after(book, plan.orders)["equity"] >= D("0.5")
    assert trim(BOOK, SLEEVES).orders == []  # 70%: above target, but not above the 75% threshold
    asked = trim(BOOK, SLEEVES, sleeve_id="equity")  # asked for explicitly: down to target
    assert [o.quantity for o in asked.orders] == [D(2)]
    assert trim(BOOK, SLEEVES, sleeve_id="gold").notes == [
        "gold is not above its target; nothing to trim."
    ]


@settings(max_examples=150, deadline=None)
@given(st.integers(1, 1000), st.integers(1, 1000), prices, prices)
def test_trimming_never_leaves_a_sleeve_under_its_target(
    a: int, b: int, pa: Decimal, pb: Decimal
) -> None:
    book = [holding(1, "equity", a, str(pa)), holding(2, "gold", b, str(pb))]
    for s in SLEEVES:
        plan = trim(book, SLEEVES, sleeve_id=s.id)
        if plan.orders:
            assert weights_after(book, plan.orders)[s.id] >= s.target


def test_rebalance_prefers_new_money_over_selling() -> None:
    book = [holding(1, "equity", 70, "10"), holding(2, "gold", 30, "10")]  # 700 / 300
    with_cash = rebalance(book, SLEEVES, cash=D(400), prefer_buys=True)
    assert {o.side for o in with_cash.orders} == {"buy"}
    after = weights_after(book, with_cash.orders)
    assert all(abs(after[s.id] - s.target) <= s.band for s in SLEEVES)  # type: ignore[operator]

    no_cash = rebalance(book, SLEEVES)
    assert [(o.side, o.sleeve) for o in no_cash.orders] == [("sell", "equity"), ("buy", "gold")]
    after = weights_after(book, no_cash.orders)
    assert all(abs(after[s.id] - s.target) <= s.band for s in SLEEVES)  # type: ignore[operator]


def test_rebalance_leaves_sleeves_inside_their_band_alone() -> None:
    book = [holding(1, "equity", 52, "10"), holding(2, "gold", 48, "10")]
    plan = rebalance(book, SLEEVES)
    assert plan.orders == [] and "inside its band" in plan.notes[0]
    assert rebalance(book, [SleeveTarget("x", D("0.5"))]).notes == [
        "No sleeve has a target and a band yet."
    ]


@settings(max_examples=100, deadline=None)
@given(st.integers(1, 5000), st.integers(1, 5000))
def test_rebalance_ends_inside_every_band_when_units_are_small(a: int, b: int) -> None:
    book = [holding(1, "equity", a, "1"), holding(2, "gold", b, "1")]
    plan = rebalance(book, SLEEVES)
    after = weights_after(book, plan.orders)
    total = total_value(book)
    for s in SLEEVES:
        # one unit of rounding is all that may remain
        assert abs(after[s.id] - s.target) <= s.band + D(2) / total  # type: ignore[operator]
