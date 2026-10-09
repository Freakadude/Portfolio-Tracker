"""Corporate actions and draft dividends (FR-MD-07)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import AuditLog
from folio.db.models_ledger import (
    CorporateAction,
    FxRate,
    Instrument,
    JobRequest,
    LedgerTransaction,
    Position,
)
from folio.jobs.market import actions_job
from folio.marketdata.base import DividendEvent, ProviderError, SplitEvent
from folio.marketdata.fake import FakeProvider
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import make_ctx, make_listing

D = Decimal
NOW = datetime(2024, 4, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


@pytest.fixture
def api(client: TestClient, owner: None) -> TestClient:
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


def new_account(api: TestClient, name: str = "Degiro") -> int:
    return api.post("/api/v1/accounts", json={"name": name}).json()["id"]  # type: ignore[no-any-return]


def buy(
    api: TestClient,
    account: int,
    instrument: int,
    day: str,
    qty: str,
    price: str = "100",
    **kw: Any,
) -> dict[str, Any]:
    r = api.post("/api/v1/transactions", json={"account_id": account, "instrument_id": instrument,
                 "type": "buy", "trade_date": day, "quantity": qty, "price": price, **kw})  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def position(db, account: int, instrument: int) -> Position:  # type: ignore[no-untyped-def]
    db.expire_all()
    return db.scalars(  # type: ignore[no-any-return]
        select(Position).where(Position.account_id == account, Position.instrument_id == instrument)
    ).one()


def run(settings: Settings, *providers: FakeProvider) -> Any:
    return actions_job(make_ctx(settings, list(providers), now=NOW))


# --- splits -----------------------------------------------------------------------------------


@pytest.fixture
def held(api: TestClient, db) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """10 units bought on 2 January 2024 for 1001 (including a 1 euro fee)."""
    instrument, listing = make_listing(db)
    db.commit()
    account = new_account(api)
    buy(api, account, instrument.id, "2024-01-02", "10", "100", fees="1")
    return {"instrument": instrument.id, "listing": listing.id, "account": account}


def splits(listing_id: int, *events: tuple[str, str]) -> FakeProvider:
    return FakeProvider(
        name="primary",
        splits={listing_id: [SplitEvent(date.fromisoformat(d), D(r)) for d, r in events]},
    )


def test_a_split_is_proposed_once_and_only_when_it_matters(
    settings: Settings, held: dict[str, Any], api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    provider = splits(
        held["listing"], ("2024-02-01", "4"), ("2023-06-01", "2"), ("2024-02-15", "1")
    )
    result = run(settings, provider)
    assert result.status == "ok" and "1 split(s)" in result.log
    db.expire_all()
    (action,) = db.scalars(select(CorporateAction)).all()
    # the 2023 split predates the first purchase; a ratio of 1 changes nothing
    assert (action.type, action.ex_date, action.ratio, action.status, action.source) == (
        "split", date(2024, 2, 1), D(4), "proposed", "primary",
    )  # fmt: skip
    assert "0 split(s)" in run(settings, provider).log  # running again proposes nothing new
    assert db.query(CorporateAction).count() == 1

    listed = api.get("/api/v1/corporate-actions").json()
    assert len(listed) == 1
    item = listed[0]
    assert (item["type"], item["ex_date"], Decimal(item["ratio"]), item["ticker"]) == (
        "split",
        "2024-02-01",
        4,
        "SXR8",
    )
    (effect,) = item["effects"]  # the preview: quantity changes, cost does not
    assert (
        Decimal(effect["quantity_before"]),
        Decimal(effect["quantity_after"]),
        Decimal(effect["cost_basis_eur"]),
    ) == (10, 40, 1001)


def test_confirming_a_one_to_four_split_quadruples_the_quantity_and_keeps_the_cost(
    settings: Settings,
    held: dict[str, Any],
    api: TestClient,
    db,  # type: ignore[no-untyped-def]
) -> None:
    run(settings, splits(held["listing"], ("2024-02-01", "4")))
    action_id = api.get("/api/v1/corporate-actions").json()[0]["id"]
    db.query(JobRequest).delete()
    db.commit()

    r = api.post(f"/api/v1/corporate-actions/{action_id}/confirm")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (
        body["status"] == "applied"
        and body["applied_at"] is not None
        and len(body["transaction_ids"]) == 1
    )
    pos = position(db, held["account"], held["instrument"])
    assert (
        pos.quantity == 40 and pos.cost_basis_eur == 1001
    )  # invariant 4: only the unit count changed
    assert pos.avg_cost_eur == D("25.025")
    tx = db.get(LedgerTransaction, body["transaction_ids"][0])
    assert tx is not None
    assert (tx.type, tx.ratio, tx.trade_date, tx.source, tx.status) == (
        "split",
        D(4),
        date(2024, 2, 1),
        "corporate_action",
        "posted",
    )
    audit = db.scalars(select(AuditLog).where(AuditLog.entity == "corporate_action")).one()
    assert (
        audit.action == "confirm"
        and audit.diff["ratio"] == "4"
        and audit.diff["transactions"] == [tx.id]
    )
    assert [
        j.params for j in db.scalars(select(JobRequest).where(JobRequest.job == "snapshots"))
    ] == [{"from": "2024-02-01"}]

    again = api.post(f"/api/v1/corporate-actions/{action_id}/confirm")
    assert again.status_code == 409 and "already applied" in again.json()["detail"]
    assert api.get("/api/v1/corporate-actions").json() == []  # nothing left to review
    assert len(api.get("/api/v1/corporate-actions?status=applied").json()) == 1


def test_trades_after_the_ex_date_are_not_multiplied(
    settings: Settings, held: dict[str, Any], api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    buy(api, held["account"], held["instrument"], "2024-02-05", "3", "30")  # quoted after the split
    run(settings, splits(held["listing"], ("2024-02-01", "4")))
    api.post(
        f"/api/v1/corporate-actions/{api.get('/api/v1/corporate-actions').json()[0]['id']}/confirm"
    )
    assert position(db, held["account"], held["instrument"]).quantity == 43  # 10 x 4 + 3


def test_a_reverse_split_halves_the_quantity(
    settings: Settings, held: dict[str, Any], api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    run(settings, splits(held["listing"], ("2024-02-01", "0.5")))
    action = api.get("/api/v1/corporate-actions").json()[0]
    assert Decimal(action["effects"][0]["quantity_after"]) == 5
    api.post(f"/api/v1/corporate-actions/{action['id']}/confirm")
    pos = position(db, held["account"], held["instrument"])
    assert (pos.quantity, pos.cost_basis_eur) == (5, 1001)


def test_a_split_applies_to_every_account_that_held_the_instrument(
    settings: Settings, held: dict[str, Any], api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    second = new_account(api, "Other")
    third = new_account(api, "Late")
    buy(api, second, held["instrument"], "2024-01-10", "4", "100")
    buy(api, third, held["instrument"], "2024-02-05", "7", "30")  # bought after the ex-date
    run(settings, splits(held["listing"], ("2024-02-01", "4")))
    action = api.get("/api/v1/corporate-actions").json()[0]
    assert sorted(e["account_name"] for e in action["effects"]) == ["Degiro", "Other"]
    done = api.post(f"/api/v1/corporate-actions/{action['id']}/confirm").json()
    assert len(done["transaction_ids"]) == 2
    assert position(db, held["account"], held["instrument"]).quantity == 40
    assert position(db, second, held["instrument"]).quantity == 16
    assert position(db, third, held["instrument"]).quantity == 7  # untouched


def test_a_dismissed_split_stays_dismissed(
    settings: Settings, held: dict[str, Any], api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    provider = splits(held["listing"], ("2024-02-01", "4"))
    run(settings, provider)
    action_id = api.get("/api/v1/corporate-actions").json()[0]["id"]
    assert (
        api.post(f"/api/v1/corporate-actions/{action_id}/dismiss").json()["status"] == "dismissed"
    )
    run(settings, provider)  # the provider still reports it
    assert api.get("/api/v1/corporate-actions").json() == []
    assert db.query(CorporateAction).count() == 1
    assert api.post(f"/api/v1/corporate-actions/{action_id}/confirm").status_code == 409
    assert api.post(f"/api/v1/corporate-actions/{action_id}/dismiss").status_code == 409
    assert position(db, held["account"], held["instrument"]).quantity == 10
    assert api.post("/api/v1/corporate-actions/999/confirm").status_code == 404


def test_requires_login(client: TestClient) -> None:
    assert client.get("/api/v1/corporate-actions").status_code == 401


# --- dividends --------------------------------------------------------------------------------


def dividends(listing_id: int, *events: tuple[str, str, str | None]) -> FakeProvider:
    return FakeProvider(
        name="primary",
        dividends={
            listing_id: [DividendEvent(date.fromisoformat(d), D(a), c) for d, a, c in events]
        },
    )


@pytest.fixture
def dist(api: TestClient, db) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """A distributing fund with 10 units held since 2 January."""
    instrument, listing = make_listing(db, ticker="DIST")
    instrument.distribution = "DIST"
    db.commit()
    account = new_account(api)
    buy(api, account, instrument.id, "2024-01-02", "10", "100")
    return {"instrument": instrument.id, "listing": listing.id, "account": account}


def drafts(api: TestClient) -> list[dict[str, Any]]:
    return api.get("/api/v1/transactions?status=draft").json()["items"]  # type: ignore[no-any-return]


def test_a_dividend_is_proposed_as_a_draft_that_stays_out_of_the_ledger(
    settings: Settings, dist: dict[str, Any], api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    result = run(settings, dividends(dist["listing"], ("2024-03-15", "0.5", "EUR")))
    assert result.status == "ok" and "1 dividend draft(s)" in result.log
    (draft,) = drafts(api)
    assert (draft["type"], draft["status"], draft["source"], draft["trade_date"]) == (
        "dividend",
        "draft",
        "corporate_action",
        "2024-03-15",
    )
    assert Decimal(draft["net_amount_eur"]) == D("5.00")  # 0.50 per unit x 10 units
    assert "0.50 EUR x 10 units" in draft["note"] and "Dated at the ex-date" in draft["note"]
    assert position(db, dist["account"], dist["instrument"]).income_eur == 0  # not yet income
    assert (
        len([t for t in api.get("/api/v1/transactions").json()["items"] if t["type"] == "dividend"])
        == 0
    )
    assert (
        "0 dividend draft(s)"
        in run(settings, dividends(dist["listing"], ("2024-03-15", "0.5", "EUR"))).log
    )


def test_confirming_a_draft_posts_it_and_the_owner_can_correct_it_first(
    settings: Settings, dist: dict[str, Any], api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    run(settings, dividends(dist["listing"], ("2024-03-15", "0.5", "EUR")))
    (draft,) = drafts(api)
    r = api.post(f"/api/v1/transactions/{draft['id']}/confirm",
                 json={"net_amount_eur": "4.20", "taxes": "0.63", "trade_date": "2024-03-20"})  # fmt: skip
    assert r.status_code == 200, r.text
    posted = r.json()
    assert (
        posted["status"],
        posted["trade_date"],
        Decimal(posted["net_amount_eur"]),
        Decimal(posted["taxes"]),
    ) == ("posted", "2024-03-20", D("4.20"), D("0.63"))
    assert position(db, dist["account"], dist["instrument"]).income_eur == D("4.20")
    actions = [
        a.action
        for a in db.scalars(
            select(AuditLog).where(
                AuditLog.entity == "transaction", AuditLog.entity_id == str(draft["id"])
            )
        )
    ]
    assert actions == ["create", "update", "confirm"]  # proposed by the worker, then corrected
    assert drafts(api) == []
    assert (
        api.post(f"/api/v1/transactions/{draft['id']}/confirm").status_code == 422
    )  # already posted
    assert api.post("/api/v1/transactions/999/confirm").status_code == 404


def test_confirming_without_changes_works_too(
    settings: Settings, dist: dict[str, Any], api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    run(settings, dividends(dist["listing"], ("2024-03-15", "0.5", "EUR")))
    (draft,) = drafts(api)
    assert api.post(f"/api/v1/transactions/{draft['id']}/confirm").status_code == 200
    assert position(db, dist["account"], dist["instrument"]).income_eur == D("5.00")


def test_a_deleted_draft_is_not_proposed_again(
    settings: Settings, dist: dict[str, Any], api: TestClient
) -> None:
    provider = dividends(dist["listing"], ("2024-03-15", "0.5", "EUR"))
    run(settings, provider)
    (draft,) = drafts(api)
    assert (
        api.delete(f"/api/v1/transactions/{draft['id']}").status_code == 204
    )  # rejecting = dismissing
    run(settings, provider)
    assert drafts(api) == []


def test_no_draft_when_the_owner_already_recorded_that_dividend(
    settings: Settings, dist: dict[str, Any], api: TestClient
) -> None:
    api.post("/api/v1/transactions", json={"account_id": dist["account"], "instrument_id": dist["instrument"],
             "type": "dividend", "trade_date": "2024-03-25", "net_amount_eur": "5"})  # fmt: skip
    run(settings, dividends(dist["listing"], ("2024-03-15", "0.5", "EUR")))
    assert (
        drafts(api) == []
    )  # a posted dividend within 45 days of the ex-date counts as the same one


def test_only_holders_at_the_ex_date_get_a_draft(
    settings: Settings, dist: dict[str, Any], api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    api.post("/api/v1/transactions", json={"account_id": dist["account"], "instrument_id": dist["instrument"],
             "type": "sell", "trade_date": "2024-03-01", "quantity": "10", "price": "110"})  # fmt: skip
    late = new_account(api, "Late")
    buy(api, late, dist["instrument"], "2024-03-20", "5")  # bought after the ex-date
    run(settings, dividends(dist["listing"], ("2024-03-15", "0.5", "EUR")))
    assert drafts(api) == []


def test_accumulating_funds_get_no_dividend_drafts_but_equities_do(
    settings: Settings, api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    acc_fund, acc_listing = make_listing(db, ticker="ACC", isin="IE0000000001")
    acc_fund.distribution = "ACC"
    equity, equity_listing = make_listing(db, ticker="EQ", isin="NL0000000002")
    equity.asset_class = "EQUITY"
    db.commit()
    account = new_account(api)
    buy(api, account, acc_fund.id, "2024-01-02", "10")
    buy(api, account, equity.id, "2024-01-02", "10")
    provider = FakeProvider(name="primary", dividends={
        acc_listing.id: [DividendEvent(date(2024, 3, 15), D("0.5"), "EUR")],
        equity_listing.id: [DividendEvent(date(2024, 3, 15), D("1.5"), "EUR")],
    })  # fmt: skip
    run(settings, provider)
    (draft,) = drafts(api)
    assert draft["instrument_id"] == equity.id and Decimal(draft["net_amount_eur"]) == D("15.00")


def test_a_dividend_in_another_currency_is_converted_with_the_ecb_rate(
    settings: Settings, api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    usd, listing = make_listing(db, ticker="USDF", currency="USD", isin="IE0000000003")
    usd.distribution = "DIST"
    db.add(FxRate(date=date(2024, 1, 2), currency="USD", rate_per_eur=D("1.25")))
    db.add(FxRate(date=date(2024, 3, 15), currency="USD", rate_per_eur=D("1.25")))
    db.commit()
    account = new_account(api)
    buy(api, account, usd.id, "2024-01-02", "10", "50")
    run(settings, dividends(listing.id, ("2024-03-15", "0.4", "USD")))
    (draft,) = drafts(api)
    assert Decimal(draft["net_amount_eur"]) == D("3.20")  # 0.40 USD x 10 units x 0.8 EUR per USD
    assert "0.40 USD" in draft["note"]


def test_a_missing_ecb_rate_is_reported_and_other_instruments_continue(
    settings: Settings, api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    usd, usd_listing = make_listing(db, ticker="USDF", currency="USD", isin="IE0000000003")
    usd.distribution = "DIST"
    eur, eur_listing = make_listing(db, ticker="EURF", isin="IE0000000004")
    eur.distribution = "DIST"
    db.add(FxRate(date=date(2024, 1, 2), currency="USD", rate_per_eur=D("1.25")))
    db.commit()
    account = new_account(api)
    buy(api, account, usd.id, "2024-01-02", "10", "50")
    buy(api, account, eur.id, "2024-01-02", "10", "100")
    provider = FakeProvider(name="primary", dividends={
        usd_listing.id: [DividendEvent(date(2024, 3, 15), D("0.4"), "JPY")],  # no JPY rates at all
        eur_listing.id: [DividendEvent(date(2024, 3, 15), D("0.5"), "EUR")],
    })  # fmt: skip
    result = run(settings, provider)
    assert result.status == "failed" and "No ECB rate for JPY" in result.log
    (draft,) = drafts(api)
    assert draft["instrument_id"] == eur.id  # the euro fund was still handled


def test_a_provider_failure_is_reported_per_instrument(
    settings: Settings, held: dict[str, Any], api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    other, _ = make_listing(db, ticker="OTHER", isin="IE0000000009")
    db.commit()
    buy(api, held["account"], other.id, "2024-01-02", "1")
    broken = FakeProvider(name="primary", error=ProviderError("HTTP 503"))
    result = run(settings, broken)
    assert result.status == "failed"
    assert result.log.count("ERROR") == 2 and "HTTP 503" in result.log  # one line per instrument
    assert db.query(Instrument).count() == 2
