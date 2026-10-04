"""Transactions API and ledger service (FR-TX-01, 02, 03, 04, 06; FR-SY-08; invariants 3 and 5)."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import Account, AuditLog
from folio.db.models_ledger import (
    FxRate,
    JobRequest,
    LedgerTransaction,
    Lot,
    LotMatch,
    Position,
)
from folio.ledger_service import insert_transaction, rebuild_account
from folio.marketdata.fx import to_eur_multiplier
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import make_listing

D = Decimal


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def api(client: TestClient, owner: None) -> TestClient:
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


@pytest.fixture
def account(api: TestClient) -> dict[str, Any]:
    return api.post("/api/v1/accounts", json={"name": "Degiro", "broker": "Degiro"}).json()  # type: ignore[no-any-return]


@pytest.fixture
def fund(db) -> int:  # type: ignore[no-untyped-def]
    instrument, _ = make_listing(db)
    db.commit()
    return instrument.id  # type: ignore[no-any-return]


def post(api: TestClient, **body: Any) -> dict[str, Any]:
    r = api.post("/api/v1/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def buy(
    api: TestClient, account_id: int, instrument_id: int, day: str, qty: str, price: str, **kw: Any
) -> dict[str, Any]:
    return post(api, account_id=account_id, instrument_id=instrument_id, type="buy", trade_date=day,
                quantity=qty, price=price, **kw)  # fmt: skip


def sell_body(
    account_id: int, instrument_id: int, day: str, qty: str, price: str, **kw: Any
) -> dict[str, Any]:
    return {"account_id": account_id, "instrument_id": instrument_id, "type": "sell",
            "trade_date": day, "quantity": qty, "price": price, **kw}  # fmt: skip


def seed_golden(api: TestClient, account_id: int, instrument_id: int) -> dict[str, Any]:
    """The hand-computed scenario from the golden fixtures: FIFO realizes 346.5, AVG 296.5."""
    buy(api, account_id, instrument_id, "2024-01-02", "10", "100", fees="1")
    buy(api, account_id, instrument_id, "2024-02-01", "10", "120", fees="1")
    return post(api, **sell_body(account_id, instrument_id, "2024-03-01", "15", "130", fees="2"))


def position(db, account_id: int) -> Position:  # type: ignore[no-untyped-def]
    db.expire_all()
    return db.scalars(select(Position).where(Position.account_id == account_id)).one()  # type: ignore[no-any-return]


def tables(db, account_id: int) -> tuple[list[tuple[Any, ...]], ...]:  # type: ignore[no-untyped-def]
    db.expire_all()
    lots = db.scalars(
        select(Lot).where(Lot.account_id == account_id).order_by(Lot.buy_transaction_id)
    )
    matches = db.scalars(
        select(LotMatch).where(LotMatch.account_id == account_id).order_by(LotMatch.id)
    )
    positions = db.scalars(
        select(Position).where(Position.account_id == account_id).order_by(Position.instrument_id)
    )
    return (
        [(x.buy_transaction_id, x.open_quantity, x.cost_eur, x.cost_native) for x in lots],
        [(x.sell_transaction_id, x.lot_buy_transaction_id, x.quantity, x.cost_eur, x.proceeds_eur, x.realized_pnl_eur) for x in matches],
        [(x.instrument_id, x.quantity, x.cost_basis_eur, x.realized_pnl_eur, x.income_eur, x.invested_eur) for x in positions],
    )  # fmt: skip


# --- FR-TX-01: every type round-trips ---------------------------------------------------------


def test_requires_login(client: TestClient) -> None:
    assert client.get("/api/v1/transactions").status_code == 401
    assert client.post("/api/v1/transactions", json={}).status_code == 401


def test_every_transaction_type_round_trips_through_the_api(
    api: TestClient, account: dict[str, Any], fund: int
) -> None:
    a = account["id"]
    sent = [
        dict(type="buy", trade_date="2024-01-02", instrument_id=fund, quantity="10", price="100", fees="1.5", note="first"),
        dict(type="buy", trade_date="2024-01-03", instrument_id=fund, quantity="5", price="102.5"),
        dict(type="sell", trade_date="2024-01-10", instrument_id=fund, quantity="3", price="110", fees="1"),
        dict(type="dividend", trade_date="2024-01-12", instrument_id=fund, net_amount_eur="4.25", taxes="0.64"),
        dict(type="interest", trade_date="2024-01-13", net_amount_eur="0.5"),
        dict(type="fee", trade_date="2024-01-14", net_amount_eur="2"),
        dict(type="tax", trade_date="2024-01-15", net_amount_eur="3"),
        dict(type="split", trade_date="2024-01-16", instrument_id=fund, ratio="2"),
        dict(type="transfer_out", trade_date="2024-01-17", instrument_id=fund, quantity="2", price="55"),
        dict(type="transfer_in", trade_date="2024-01-18", instrument_id=fund, quantity="2", price="55", net_amount_eur="110"),
        dict(type="deposit", trade_date="2024-01-19", net_amount_eur="1000"),
        dict(type="withdrawal", trade_date="2024-01-20", net_amount_eur="200"),
    ]  # fmt: skip
    created = [post(api, account_id=a, **body) for body in sent]
    page = api.get("/api/v1/transactions?limit=50").json()
    assert len(page["items"]) == 12 and page["next_cursor"] is None
    by_id = {t["id"]: t for t in page["items"]}
    for body, made in zip(sent, created, strict=True):
        got = by_id[made["id"]]
        assert got["type"] == body["type"] and got["trade_date"] == body["trade_date"]
        assert got["account_name"] == "Degiro" and got["status"] == "posted"
        assert got["source"] == "manual"
        for key in ("quantity", "price", "fees", "taxes", "ratio"):
            if key in body:
                assert Decimal(got[key]) == Decimal(body[key]), key
        if body["type"] in ("dividend", "interest", "fee", "tax", "deposit", "withdrawal"):
            assert Decimal(got["net_amount_eur"]) == Decimal(body["net_amount_eur"])
        assert got["note"] == body.get("note")
    assert (
        by_id[created[0]["id"]]["ticker"] == "SXR8" and by_id[created[0]["id"]]["currency"] == "EUR"
    )
    # trades store the cash effect in EUR, comparable with the broker statement
    assert Decimal(by_id[created[0]["id"]]["net_amount_eur"]) == D(
        "-1001.5"
    )  # buy: 1000 + 1.5 fees
    assert Decimal(by_id[created[2]["id"]]["net_amount_eur"]) == D("329")  # sell: 330 - 1 fee


def test_the_form_rules_each_type_needs_are_enforced_in_plain_language(
    api: TestClient, account: dict[str, Any], fund: int
) -> None:
    a = account["id"]

    def bad(**body: Any) -> dict[str, Any]:
        r = api.post(
            "/api/v1/transactions", json={"account_id": a, "trade_date": "2024-01-02", **body}
        )
        assert r.status_code == 422, r.text
        assert r.headers["content-type"].startswith("application/problem+json")
        return {e["field"]: e["message"] for e in r.json()["errors"]}

    assert bad(type="buy", quantity="1", price="1")["instrument_id"] == "A buy needs an instrument."
    assert (
        "greater than zero"
        in bad(type="buy", instrument_id=fund, quantity="0", price="1")["quantity"]
    )
    assert "needs a price" in bad(type="buy", instrument_id=fund, quantity="1")["price"]
    assert "needs a ratio" in bad(type="split", instrument_id=fund)["ratio"]
    assert "amount in euros" in bad(type="dividend", instrument_id=fund)["net_amount_eur"]
    assert "amount in euros" in bad(type="deposit")["net_amount_eur"]
    assert (
        bad(type="dividend", net_amount_eur="5")["instrument_id"]
        == "A dividend needs an instrument."
    )
    assert (
        "does not exist"
        in bad(type="buy", instrument_id=9999, quantity="1", price="1")["instrument_id"]
    )
    assert (
        "three-letter code"
        in bad(type="buy", instrument_id=fund, quantity="1", price="1", currency="euro")["currency"]
    )
    future = api.post(
        "/api/v1/transactions",
        json={
            "account_id": a,
            "type": "deposit",
            "trade_date": "2999-01-01",
            "net_amount_eur": "1",
        },
    )
    assert (
        future.status_code == 422
        and "cannot be in the future" in future.json()["errors"][0]["message"]
    )
    early = api.post(
        "/api/v1/transactions",
        json={
            "account_id": a,
            "type": "deposit",
            "trade_date": "2024-01-02",
            "settle_date": "2024-01-01",
            "net_amount_eur": "1",
        },
    )
    assert "before the trade date" in early.json()["errors"][0]["message"]
    ghost = api.post(
        "/api/v1/transactions",
        json={
            "account_id": 999,
            "type": "deposit",
            "trade_date": "2024-01-02",
            "net_amount_eur": "1",
        },
    )
    assert "account does not exist" in ghost.json()["errors"][0]["message"]
    negative = api.post(
        "/api/v1/transactions",
        json={
            "account_id": a,
            "type": "buy",
            "trade_date": "2024-01-02",
            "instrument_id": fund,
            "quantity": "1",
            "price": "1",
            "fees": "-1",
        },
    )
    assert negative.status_code == 422
    assert api.get("/api/v1/transactions").json()["items"] == []  # nothing was saved


# --- FR-TX-02: FX prefilled from the ECB, overridable -----------------------------------------


def add_usd_rates(db) -> None:  # type: ignore[no-untyped-def]
    db.add_all(
        [
            FxRate(date=date(2024, 12, 19), currency="USD", rate_per_eur=D("1.0400")),
            FxRate(date=date(2024, 12, 20), currency="USD", rate_per_eur=D("1.0462")),
        ]
    )
    db.commit()


def test_fx_rate_is_prefilled_from_the_ecb_and_used_in_the_cost_basis(
    api: TestClient, account: dict[str, Any], db
) -> None:  # type: ignore[no-untyped-def]
    add_usd_rates(db)
    instrument, _ = make_listing(db, ticker="AAA", currency="USD", isin="IE0000000001")
    db.commit()
    made = buy(api, account["id"], instrument.id, "2024-12-21", "10", "50")  # a Saturday
    expected = to_eur_multiplier(D("1.0462"))  # Friday's rate
    assert made["currency"] == "USD" and Decimal(made["fx_rate_to_eur"]) == expected
    assert position(db, account["id"]).cost_basis_eur == D(10) * D(50) * expected


def test_an_overridden_broker_rate_is_what_the_cost_basis_uses(
    api: TestClient, account: dict[str, Any], db
) -> None:  # type: ignore[no-untyped-def]
    add_usd_rates(db)
    instrument, _ = make_listing(db, ticker="AAA", currency="USD", isin="IE0000000001")
    db.commit()
    made = buy(
        api,
        account["id"],
        instrument.id,
        "2024-12-20",
        "10",
        "50",
        fx_rate_to_eur="0.9",
        fees="2",
        fees_currency="USD",
        fees_fx_rate_to_eur="0.95",
    )
    assert Decimal(made["fx_rate_to_eur"]) == D("0.9") and Decimal(
        made["fees_fx_rate_to_eur"]
    ) == D("0.95")
    assert position(db, account["id"]).cost_basis_eur == D("10") * D("50") * D("0.9") + D("2") * D(
        "0.95"
    )  # 451.9


def test_fees_in_their_own_currency_get_their_own_ecb_rate(
    api: TestClient, account: dict[str, Any], fund: int, db
) -> None:  # type: ignore[no-untyped-def]
    add_usd_rates(db)
    made = buy(api, account["id"], fund, "2024-12-20", "10", "100", fees="3", fees_currency="usd")
    assert made["fees_currency"] == "USD" and made["currency"] == "EUR"
    assert Decimal(made["fees_fx_rate_to_eur"]) == to_eur_multiplier(D("1.0462"))
    assert made["fx_rate_to_eur"] == "1"


def test_a_missing_ecb_rate_asks_the_owner_for_one(
    api: TestClient, account: dict[str, Any], db
) -> None:  # type: ignore[no-untyped-def]
    instrument, _ = make_listing(db, ticker="AAA", currency="JPY", isin="IE0000000001")
    db.commit()
    r = api.post(
        "/api/v1/transactions",
        json={
            "account_id": account["id"],
            "instrument_id": instrument.id,
            "type": "buy",
            "trade_date": "2024-12-20",
            "quantity": "1",
            "price": "100",
        },
    )
    assert r.status_code == 422
    error = r.json()["errors"][0]
    assert error["field"] == "fx_rate_to_eur" and "No ECB rate for JPY" in error["message"]
    assert "enter the exchange rate yourself" in error["message"]
    ok = api.post(
        "/api/v1/transactions",
        json={
            "account_id": account["id"],
            "instrument_id": instrument.id,
            "type": "buy",
            "trade_date": "2024-12-20",
            "quantity": "1",
            "price": "100",
            "fx_rate_to_eur": "0.0062",
        },
    )
    assert ok.status_code == 201


def test_fx_prefill_endpoint_for_the_form(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    add_usd_rates(db)
    r = api.get("/api/v1/transactions/fx-prefill?currency=usd&date=2024-12-21")
    assert r.status_code == 200
    body = r.json()
    assert (body["currency"], body["rate_per_eur"], body["rate_date"]) == (
        "USD",
        "1.0462",
        "2024-12-20",
    )
    assert Decimal(body["fx_rate_to_eur"]) == to_eur_multiplier(D("1.0462"))
    assert (
        api.get("/api/v1/transactions/fx-prefill?currency=JPY&date=2024-12-21").status_code == 422
    )


def test_changing_the_date_keeps_an_overridden_rate_but_refreshes_a_prefilled_one(
    api: TestClient, account: dict[str, Any], db
) -> None:  # type: ignore[no-untyped-def]
    add_usd_rates(db)
    instrument, _ = make_listing(db, ticker="AAA", currency="USD", isin="IE0000000001")
    db.commit()
    prefilled = buy(api, account["id"], instrument.id, "2024-12-20", "1", "10")
    overridden = buy(
        api, account["id"], instrument.id, "2024-12-20", "1", "10", fx_rate_to_eur="0.9"
    )
    for tx_id in (prefilled["id"], overridden["id"]):
        r = api.patch(f"/api/v1/transactions/{tx_id}", json={"trade_date": "2024-12-19"})
        assert r.status_code == 200, r.text
    rates = {
        t["id"]: Decimal(t["fx_rate_to_eur"])
        for t in api.get("/api/v1/transactions").json()["items"]
    }
    assert rates[prefilled["id"]] == to_eur_multiplier(
        D("1.0400")
    )  # followed the new day's ECB rate
    assert rates[overridden["id"]] == D("0.9")  # the owner's broker rate was kept


# --- FR-TX-04: the sell preview ---------------------------------------------------------------


def test_sell_preview_equals_the_saved_result_to_the_cent(
    api: TestClient, account: dict[str, Any], fund: int, db
) -> None:  # type: ignore[no-untyped-def]
    a = account["id"]
    buy(api, a, fund, "2024-01-02", "10", "100", fees="1")
    buy(api, a, fund, "2024-02-01", "10", "120", fees="1")
    body = sell_body(a, fund, "2024-03-01", "15", "130", fees="2")
    before = (
        api.get("/api/v1/transactions").json()["items"],
        db.query(AuditLog).count(),
        db.query(JobRequest).count(),
    )

    preview = api.post("/api/v1/transactions/preview-sell", json=body)
    assert preview.status_code == 200, preview.text
    p = preview.json()
    assert [(m["lot_trade_date"], m["quantity"], Decimal(m["cost_eur"])) for m in p["matches"]] == [
        ("2024-01-02", "10", D("1001")), ("2024-02-01", "5", D("600.5")),
    ]  # fmt: skip
    assert Decimal(p["net_proceeds_eur"]) == D("1948") and Decimal(p["cost_eur"]) == D("1601.5")
    assert Decimal(p["realized_pnl_eur"]) == D("346.5")
    assert abs(Decimal(p["realized_pct"]) - D("346.5") / D("1601.5")) < D("1E-12")
    assert p["remaining_quantity"] == "5" and Decimal(p["remaining_cost_basis_eur"]) == D("600.5")
    # a preview writes nothing: no transaction, no audit row, no job request
    after = (
        api.get("/api/v1/transactions").json()["items"],
        db.query(AuditLog).count(),
        db.query(JobRequest).count(),
    )
    assert after == before

    saved = post(api, **body)
    db.expire_all()
    rows = db.scalars(
        select(LotMatch).where(LotMatch.sell_transaction_id == saved["id"]).order_by(LotMatch.id)
    ).all()
    assert [(r.quantity, r.cost_eur, r.proceeds_eur, r.realized_pnl_eur) for r in rows] == [
        (D(m["quantity"]), D(m["cost_eur"]), D(m["proceeds_eur"]), D(m["realized_pnl_eur"]))
        for m in p["matches"]
    ]
    pos = position(db, a)
    assert (pos.quantity, pos.cost_basis_eur, pos.realized_pnl_eur) == (
        D(p["remaining_quantity"]),
        D(p["remaining_cost_basis_eur"]),
        D(p["realized_pnl_eur"]),
    )


def test_sell_preview_refuses_an_oversell_and_other_types(
    api: TestClient, account: dict[str, Any], fund: int
) -> None:
    buy(api, account["id"], fund, "2024-01-02", "10", "100")
    too_big = api.post(
        "/api/v1/transactions/preview-sell",
        json=sell_body(account["id"], fund, "2024-03-01", "11", "100"),
    )
    assert too_big.status_code == 422
    assert "Cannot sell 11 units on 2024-03-01: only 10 are held" in too_big.json()["detail"]
    wrong = api.post(
        "/api/v1/transactions/preview-sell",
        json={
            "account_id": account["id"],
            "type": "buy",
            "trade_date": "2024-03-01",
            "instrument_id": fund,
            "quantity": "1",
            "price": "1",
        },
    )
    assert wrong.status_code == 422 and "Only a sell can be previewed" in wrong.json()["detail"]


# --- invariant 3: an oversell is rejected and nothing is saved --------------------------------


def test_an_oversell_is_rejected_and_nothing_is_kept(
    api: TestClient, account: dict[str, Any], fund: int, db
) -> None:  # type: ignore[no-untyped-def]
    a = account["id"]
    buy(api, a, fund, "2024-01-02", "10", "100")
    snapshot_before = tables(db, a)
    audits, jobs = db.query(AuditLog).count(), db.query(JobRequest).count()
    r = api.post("/api/v1/transactions", json=sell_body(a, fund, "2024-02-01", "10.5", "100"))
    assert r.status_code == 422
    assert "Cannot sell 10.5 units on 2024-02-01: only 10 are held" in r.json()["detail"]
    assert len(api.get("/api/v1/transactions").json()["items"]) == 1
    assert tables(db, a) == snapshot_before
    assert (db.query(AuditLog).count(), db.query(JobRequest).count()) == (audits, jobs)


def test_edits_and_deletes_that_would_oversell_are_refused(
    api: TestClient, account: dict[str, Any], fund: int, db
) -> None:  # type: ignore[no-untyped-def]
    a = account["id"]
    first = buy(api, a, fund, "2024-01-02", "10", "100")
    sale = post(api, **sell_body(a, fund, "2024-02-01", "8", "110"))
    snapshot_before = tables(db, a)
    grow = api.patch(f"/api/v1/transactions/{sale['id']}", json={"quantity": "11"})
    assert grow.status_code == 422 and "only 10 are held" in grow.json()["detail"]
    shrink_buy = api.patch(f"/api/v1/transactions/{first['id']}", json={"quantity": "5"})
    assert shrink_buy.status_code == 422 and "only 5 are held" in shrink_buy.json()["detail"]
    remove_buy = api.delete(f"/api/v1/transactions/{first['id']}")
    assert remove_buy.status_code == 422 and "only 0 are held" in remove_buy.json()["detail"]
    assert (
        tables(db, a) == snapshot_before
        and len(api.get("/api/v1/transactions").json()["items"]) == 2
    )


# --- FR-TX-06, FR-SY-08: edits rebuild derived data and are audited ---------------------------


def test_a_backdated_buy_rebuilds_lots_and_positions_and_asks_for_new_snapshots(
    api: TestClient, account: dict[str, Any], fund: int, db
) -> None:  # type: ignore[no-untyped-def]
    a = account["id"]
    buy(api, a, fund, "2024-03-01", "10", "120")
    assert position(db, a).first_trade_date == date(2024, 3, 1)
    db.query(JobRequest).delete()
    db.commit()
    buy(api, a, fund, "2024-01-02", "5", "100")  # backdated
    pos = position(db, a)
    assert (pos.quantity, pos.cost_basis_eur, pos.first_trade_date) == (
        D(15),
        D(1700),
        date(2024, 1, 2),
    )
    lots = tables(db, a)[
        0
    ]  # ordered by the buy transaction id: March first, then the backdated one
    assert [(q, c) for _, q, c, _ in lots] == [(D(10), D(1200)), (D(5), D(500))]
    requests = db.scalars(select(JobRequest)).all()
    assert [(r.job, r.params, r.status) for r in requests] == [
        ("snapshots", {"from": "2024-01-02"}, "pending")
    ]


def test_update_and_delete_are_audited_with_old_and_new_values(
    api: TestClient, account: dict[str, Any], fund: int, db
) -> None:  # type: ignore[no-untyped-def]
    a = account["id"]
    made = buy(api, a, fund, "2024-01-02", "10", "100", note="typo")
    r = api.patch(
        f"/api/v1/transactions/{made['id']}",
        json={"price": "101.5", "note": "fixed", "trade_date": "2024-01-03"},
    )
    assert r.status_code == 200 and Decimal(r.json()["price"]) == D("101.5")
    update = db.scalars(
        select(AuditLog).where(AuditLog.entity == "transaction", AuditLog.action == "update")
    ).one()
    assert update.entity_id == str(made["id"]) and update.actor == "user"
    assert update.diff["price"] == {"old": "100", "new": "101.5"}
    assert update.diff["note"] == {"old": "typo", "new": "fixed"}
    assert update.diff["trade_date"] == {"old": "2024-01-02", "new": "2024-01-03"}
    assert "quantity" not in update.diff  # unchanged fields are not listed
    jobs = [
        r.params["from"]
        for r in db.scalars(select(JobRequest).where(JobRequest.job == "snapshots"))
    ]
    assert "2024-01-02" in jobs  # snapshots from the earliest affected day are redone

    assert api.delete(f"/api/v1/transactions/{made['id']}").status_code == 204
    gone = db.scalars(select(AuditLog).where(AuditLog.action == "delete")).one()
    assert gone.diff["quantity"] == "10" and gone.diff["price"] == "101.5"
    assert api.get("/api/v1/transactions").json()["items"] == []
    assert db.get(LedgerTransaction, made["id"]).deleted_at is not None  # type: ignore[union-attr]
    assert api.delete(f"/api/v1/transactions/{made['id']}").status_code == 404
    assert api.patch(f"/api/v1/transactions/{made['id']}", json={"note": "x"}).status_code == 404
    created = db.scalars(
        select(AuditLog).where(AuditLog.action == "create", AuditLog.entity == "transaction")
    ).one()
    assert created.diff["note"] == "typo"


def test_derived_tables_are_identical_after_a_second_rebuild(
    api: TestClient, account: dict[str, Any], fund: int, db
) -> None:  # type: ignore[no-untyped-def]
    a = account["id"]
    seed_golden(api, a, fund)
    post(
        api,
        account_id=a,
        instrument_id=fund,
        type="dividend",
        trade_date="2024-03-05",
        net_amount_eur="5",
    )
    first = tables(db, a)
    account_row = db.get(Account, a)
    rebuild_account(db, account_row)  # type: ignore[arg-type]
    db.commit()
    rebuild_account(db, account_row)  # type: ignore[arg-type]
    db.commit()
    assert tables(db, a) == first  # invariant 5


def test_draft_transactions_never_reach_the_ledger(
    api: TestClient, account: dict[str, Any], fund: int, db
) -> None:  # type: ignore[no-untyped-def]
    a = account["id"]
    buy(api, a, fund, "2024-01-02", "10", "100")
    insert_transaction(
        db,
        {
            "account_id": a,
            "instrument_id": fund,
            "type": "dividend",
            "trade_date": date(2024, 2, 1),
            "net_amount_eur": D(7),
        },
        source="corporate_action",
        status="draft",
    )
    db.commit()
    account_row = db.get(Account, a)
    rebuild_account(db, account_row)  # type: ignore[arg-type]
    db.commit()
    assert position(db, a).income_eur == D(0)
    assert len(api.get("/api/v1/transactions").json()["items"]) == 1
    drafts = api.get("/api/v1/transactions?status=draft").json()["items"]
    assert [(t["type"], t["status"], t["source"]) for t in drafts] == [
        ("dividend", "draft", "corporate_action")
    ]
    assert len(api.get("/api/v1/transactions?status=all").json()["items"]) == 2


# --- FR-TX-03: the cost-basis method ----------------------------------------------------------


def test_switching_the_cost_basis_method_recomputes_and_is_audited(
    api: TestClient, account: dict[str, Any], fund: int, db
) -> None:  # type: ignore[no-untyped-def]
    a = account["id"]
    seed_golden(api, a, fund)
    pos = position(db, a)
    assert (pos.quantity, pos.cost_basis_eur, pos.realized_pnl_eur) == (
        D(5),
        D("600.5"),
        D("346.5"),
    )  # FIFO
    db.query(JobRequest).delete()
    db.commit()

    r = api.patch(f"/api/v1/accounts/{a}", json={"cost_basis_method": "AVG"})
    assert r.status_code == 200 and r.json()["cost_basis_method"] == "AVG"
    pos = position(db, a)
    assert (pos.quantity, pos.cost_basis_eur, pos.realized_pnl_eur) == (
        D(5),
        D("550.5"),
        D("296.5"),
    )  # AVG
    assert len(tables(db, a)[0]) == 1  # one pooled lot
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "cost_basis_method")).one()
    assert audit.diff == {"cost_basis_method": {"old": "FIFO", "new": "AVG"}}
    assert db.scalars(select(JobRequest)).one().params == {"from": "2024-01-02"}

    api.patch(f"/api/v1/accounts/{a}", json={"cost_basis_method": "FIFO"})
    assert position(db, a).realized_pnl_eur == D("346.5")  # and back again
    assert api.patch(f"/api/v1/accounts/{a}", json={"cost_basis_method": "LIFO"}).status_code == 422


# --- listing ----------------------------------------------------------------------------------


def test_filters_and_cursor_pagination(
    api: TestClient, account: dict[str, Any], fund: int, db
) -> None:  # type: ignore[no-untyped-def]
    other = api.post("/api/v1/accounts", json={"name": "Other"}).json()["id"]
    a = account["id"]
    for day in ("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-05"):
        buy(api, a, fund, day, "1", "10")
    post(api, account_id=other, type="deposit", trade_date="2024-01-06", net_amount_eur="50")
    page1 = api.get("/api/v1/transactions?limit=2").json()
    assert [t["trade_date"] for t in page1["items"]] == ["2024-01-06", "2024-01-05"] and page1[
        "next_cursor"
    ]
    seen = [t["id"] for t in page1["items"]]
    cursor = page1["next_cursor"]
    while cursor:
        page = api.get(f"/api/v1/transactions?limit=2&cursor={cursor}").json()
        seen += [t["id"] for t in page["items"]]
        cursor = page["next_cursor"]
    assert len(seen) == 6 and len(set(seen)) == 6  # every row exactly once, newest first
    assert api.get("/api/v1/transactions?limit=2&cursor=garbage").status_code == 422
    assert len(api.get(f"/api/v1/transactions?account={other}").json()["items"]) == 1
    assert len(api.get(f"/api/v1/transactions?instrument={fund}").json()["items"]) == 5
    assert len(api.get("/api/v1/transactions?type=deposit").json()["items"]) == 1
    window = api.get("/api/v1/transactions?from=2024-01-03&to=2024-01-04").json()["items"]
    assert sorted(t["trade_date"] for t in window) == ["2024-01-03", "2024-01-04"]
    assert api.get("/api/v1/transactions?status=nonsense").status_code == 422


# --- accounts ---------------------------------------------------------------------------------


def test_accounts_crud_and_protection(api: TestClient, fund: int) -> None:
    created = api.post(
        "/api/v1/accounts", json={"name": "  Pension ", "broker": "X", "cost_basis_method": "AVG"}
    )
    assert created.status_code == 201
    acc = created.json()
    assert (
        acc["name"],
        acc["cost_basis_method"],
        acc["transaction_count"],
        acc["base_currency"],
    ) == ("Pension", "AVG", 0, "EUR")
    renamed = api.patch(
        f"/api/v1/accounts/{acc['id']}", json={"name": "Pension 2", "active": False}
    )
    assert (renamed.json()["name"], renamed.json()["active"]) == ("Pension 2", False)
    buy(api, acc["id"], fund, "2024-01-02", "1", "10")
    listed = {a["name"]: a for a in api.get("/api/v1/accounts").json()}
    assert listed["Pension 2"]["transaction_count"] == 1
    blocked = api.delete(f"/api/v1/accounts/{acc['id']}")
    assert blocked.status_code == 409 and "has 1 transaction" in blocked.json()["detail"]
    empty = api.post("/api/v1/accounts", json={"name": "Empty"}).json()
    assert api.delete(f"/api/v1/accounts/{empty['id']}").status_code == 204
    assert "Empty" not in {a["name"] for a in api.get("/api/v1/accounts").json()}
    assert api.patch("/api/v1/accounts/999", json={"name": "x"}).status_code == 404
