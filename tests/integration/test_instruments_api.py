"""Instruments API: resolve by ISIN, manual instruments, edit, archive, delete
(FR-INS-01, FR-INS-02, FR-INS-03)."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from tenacity import wait_none

from folio.config import Settings
from folio.db.engine import make_engine, make_session_factory
from folio.db.models import Account, AuditLog
from folio.db.models_ledger import JobRequest, LedgerTransaction, Listing, PriceBar
from tests.conftest import PASSWORD, USERNAME
from tests.marketdata_helpers import Scripted, respond

SXR8 = "IE00B5BMR087"


def provider_handler(request: httpx.Request) -> httpx.Response:
    """The recorded OpenFIGI answer and Yahoo's recorded chart for SXR8.DE; everything else
    is unknown to Yahoo (404), as a symbol that does not exist would be."""
    url = str(request.url)
    if "openfigi.com" in url:
        body = request.read().decode()
        return respond("openfigi_sxr8.json" if SXR8 in body else "openfigi_warning.json")
    if "/v8/finance/chart/SXR8.DE" in url:
        return respond("yahoo_sxr8_de.json")
    return httpx.Response(404, json={})


@pytest.fixture
def scripted() -> Scripted:
    return Scripted(provider_handler)


@pytest.fixture
def api(make_client: Callable[..., TestClient], owner: None, scripted: Scripted) -> TestClient:
    client = make_client(
        provider_transport=scripted.transport, provider_http_options={"wait": wait_none()}
    )
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return client


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    with make_session_factory(make_engine(settings.db_url))() as session:
        yield session


def sxr8_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "isin": SXR8,
        "name": "iShares Core S&P 500 UCITS ETF",
        "asset_class": "ETF",
        "issuer": "iShares",
        "domicile": "IE",
        "distribution": "ACC",
        "listing": {"mic": "XETR", "ticker": "SXR8", "currency": "EUR"},
    }
    return body | overrides


def test_everything_requires_a_login(client: TestClient) -> None:
    assert client.get("/api/v1/instruments").status_code == 401
    assert client.get(f"/api/v1/instruments/resolve?isin={SXR8}").status_code == 401


def test_resolving_an_isin_lists_its_xetra_and_euronext_listings(api: TestClient) -> None:
    r = api.get(f"/api/v1/instruments/resolve?isin={SXR8.lower()}")
    assert r.status_code == 200
    body = r.json()
    assert (body["isin"], body["name"], body["asset_class"], body["domicile"]) == (
        SXR8, "iShares Core S&P 500", "ETF", "IE",
    )  # fmt: skip
    assert body["issuer"] == "iShares"
    by_key = {(c["mic"], c["ticker"]): c for c in body["candidates"]}
    xetra, amsterdam = by_key[("XETR", "SXR8")], by_key[("XAMS", "CSPX")]
    assert xetra["exchange_name"] == "Xetra" and amsterdam["exchange_name"] == "Euronext Amsterdam"
    # the recorded Yahoo metadata confirms Xetra's trading currency...
    assert (xetra["currency"], xetra["currency_confirmed"], xetra["confirmed_by"]) == (
        "EUR", True, "yahoo",
    )  # fmt: skip
    # ...while a listing nobody could confirm is flagged as a guess
    assert amsterdam["currency_confirmed"] is False
    assert "guess" in amsterdam["warning"] and "Check it before" in amsterdam["warning"]
    # candidates are ordered Xetra first, then the other exchanges
    assert [c["mic"] for c in body["candidates"]][0] == "XETR"
    assert {"XLON", "XMIL", "XSWX"} <= {c["mic"] for c in body["candidates"]}


def test_resolve_rejects_bad_isins_in_plain_language(api: TestClient) -> None:
    wrong_digit = api.get("/api/v1/instruments/resolve?isin=IE00B5BMR088")
    assert wrong_digit.status_code == 422 and "wrong check digit" in wrong_digit.json()["detail"]
    malformed = api.get("/api/v1/instruments/resolve?isin=hello")
    assert malformed.status_code == 422 and "12 characters" in malformed.json()["detail"]


def test_resolve_of_an_unknown_isin_returns_no_candidates(api: TestClient) -> None:
    r = api.get("/api/v1/instruments/resolve?isin=US0378331005")  # valid, but the fake knows none
    assert r.status_code == 200 and r.json()["candidates"] == [] and r.json()["name"] == ""


def test_resolve_reports_an_unreachable_lookup_service(
    make_client: Callable[..., TestClient], owner: None
) -> None:
    down = Scripted(lambda r: httpx.Response(503, text="down"))
    client = make_client(
        provider_transport=down.transport, provider_http_options={"wait": wait_none()}
    )
    client.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
    r = client.get(f"/api/v1/instruments/resolve?isin={SXR8}")
    assert r.status_code == 502 and "Could not look up this ISIN" in r.json()["detail"]


def test_picking_a_listing_creates_the_instrument_and_queues_a_backfill(
    api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    r = api.post("/api/v1/instruments", json=sxr8_body())
    assert r.status_code == 201
    body = r.json()
    assert (body["isin"], body["status"], body["manual"], body["stale"]) == (
        SXR8,
        "active",
        False,
        True,
    )
    (listing,) = body["listings"]
    assert listing["primary"] and (listing["mic"], listing["ticker"], listing["currency"]) == (
        "XETR", "SXR8", "EUR",
    )  # fmt: skip
    # symbols are built on the server from the exchange table, never taken from the client
    assert listing["provider_symbols"] == {"yahoo": "SXR8.DE", "eodhd": "SXR8.XETRA"}

    request = db.scalars(select(JobRequest)).one()
    assert (request.job, request.status, request.params) == (
        "backfill",
        "pending",
        {"listing_id": listing["id"]},
    )  # picking a listing triggers the price backfill
    audit = db.scalars(select(AuditLog).where(AuditLog.entity == "instrument")).one()
    assert audit.action == "create" and audit.diff["isin"] == SXR8


def test_adding_the_same_isin_twice_is_refused(api: TestClient) -> None:
    assert api.post("/api/v1/instruments", json=sxr8_body()).status_code == 201
    again = api.post("/api/v1/instruments", json=sxr8_body())
    assert again.status_code == 409 and "already added" in again.json()["detail"]


def test_listing_on_an_unsupported_exchange_and_invalid_input(api: TestClient) -> None:
    odd = api.post(
        "/api/v1/instruments",
        json=sxr8_body(listing={"mic": "XTKS", "ticker": "X", "currency": "JPY"}),
    )
    assert (
        odd.status_code == 422 and "cannot price listings on exchange XTKS" in odd.json()["detail"]
    )
    no_listing = api.post(
        "/api/v1/instruments", json={"name": "X", "asset_class": "ETF", "isin": SXR8}
    )
    assert no_listing.status_code == 422
    bad_currency = api.post(
        "/api/v1/instruments",
        json=sxr8_body(listing={"mic": "XETR", "ticker": "SXR8", "currency": "euro"}),
    )
    assert bad_currency.status_code == 422
    bad_isin = api.post("/api/v1/instruments", json=sxr8_body(isin="IE00B5BMR088"))
    assert bad_isin.status_code == 422 and "check digit" in bad_isin.json()["detail"]


def test_a_manual_instrument_values_from_a_hand_entered_price(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    r = api.post(
        "/api/v1/instruments",
        json={"name": "Private bond", "asset_class": "BOND", "manual": True, "currency": "eur",
              "coupon_pct": "3.5", "maturity_date": "2030-06-30", "rating": "BBB"},
    )  # fmt: skip
    assert r.status_code == 201
    body = r.json()
    assert (body["manual"], body["isin"], body["coupon_pct"], body["maturity_date"]) == (
        True, None, "3.5", "2030-06-30",
    )  # fmt: skip
    assert body["listings"][0]["mic"] == "MANUAL" and body["listings"][0]["currency"] == "EUR"
    assert body["last_close"] is None
    assert db.scalars(select(JobRequest)).all() == []  # nothing to backfill

    price = api.post(
        f"/api/v1/instruments/{body['id']}/prices", json={"date": "2024-03-01", "close": "98.75"}
    )
    assert (
        price.status_code == 201
        and price.json()["source"] == "manual"
        and price.json()["overridden"]
    )
    again = api.post(
        f"/api/v1/instruments/{body['id']}/prices", json={"date": "2024-04-01", "close": "99.1"}
    )
    assert again.status_code == 201
    shown = api.get(f"/api/v1/instruments/{body['id']}").json()
    assert shown["last_close"] == {
        "date": "2024-04-01",
        "close": "99.1",
        "source": "manual",
        "overridden": True,
    }
    assert shown["stale"] is False  # hand-priced instruments are never flagged stale
    history = api.get(f"/api/v1/instruments/{body['id']}/prices?from=2024-03-15").json()
    assert [p["date"] for p in history] == ["2024-04-01"]
    assert (
        api.post(
            f"/api/v1/instruments/{body['id']}/prices", json={"date": "2024-05-01", "close": "0"}
        ).status_code
        == 422
    )


def test_the_issuers_product_page_is_saved_checked_audited_and_cleared(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    created = api.post("/api/v1/instruments", json=sxr8_body()).json()
    path = f"/api/v1/instruments/{created['id']}"
    assert created["product_url"] is None
    page = "https://www.ishares.com/nl/particuliere-belegger/nl/producten/253743/"
    r = api.patch(path, json={"product_url": f"  {page}  "})
    assert r.status_code == 200 and r.json()["product_url"] == page  # trimmed
    assert api.get(path).json()["product_url"] == page
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "update")).all()[-1]
    assert audit.diff["product_url"] == {"old": None, "new": page}
    # only plain web addresses: a script or a bare word is refused and nothing changes
    for bad in ("javascript:alert(1)", "ishares.com/page", "ftp://x.org/a", "https://"):
        assert api.patch(path, json={"product_url": bad}).status_code == 422, bad
    assert api.get(path).json()["product_url"] == page
    assert api.patch(path, json={"name": "Other"}).json()["product_url"] == page  # untouched
    assert api.patch(path, json={"product_url": "  "}).json()["product_url"] is None  # cleared


def test_manual_instruments_need_a_currency(api: TestClient) -> None:
    r = api.post("/api/v1/instruments", json={"name": "X", "asset_class": "FUND", "manual": True})
    assert r.status_code == 422


def test_editing_an_instrument_is_audited_with_old_and_new_values(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    created = api.post("/api/v1/instruments", json=sxr8_body()).json()
    r = api.patch(
        f"/api/v1/instruments/{created['id']}",
        json={
            "name": "iShares S&P 500",
            "ter_pct": "0.07",
            "tags": ["core", "us"],
            "domicile": "ie",
        },
    )
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["ter_pct"], r.json()["tags"]) == (
        "iShares S&P 500",
        "0.07",
        ["core", "us"],
    )
    audits = db.scalars(select(AuditLog).where(AuditLog.action == "update")).all()
    assert len(audits) == 1
    assert audits[0].diff["name"] == {
        "old": "iShares Core S&P 500 UCITS ETF",
        "new": "iShares S&P 500",
    }
    assert audits[0].diff["ter_pct"] == {"old": None, "new": "0.07"}
    assert (
        api.patch(f"/api/v1/instruments/{created['id']}", json={"asset_class": "STOCK"}).status_code
        == 422
    )
    assert api.patch("/api/v1/instruments/999", json={"name": "x"}).status_code == 404


def test_archiving_hides_an_instrument_from_the_default_list(api: TestClient) -> None:
    created = api.post("/api/v1/instruments", json=sxr8_body()).json()
    api.patch(f"/api/v1/instruments/{created['id']}", json={"status": "archived"})
    assert api.get("/api/v1/instruments").json() == []
    assert [i["id"] for i in api.get("/api/v1/instruments?status=archived").json()] == [
        created["id"]
    ]
    assert len(api.get("/api/v1/instruments?status=all").json()) == 1
    api.patch(f"/api/v1/instruments/{created['id']}", json={"status": "active"})
    assert len(api.get("/api/v1/instruments").json()) == 1
    assert api.get("/api/v1/instruments?status=bogus").status_code == 422


def add_transaction(db, instrument_id: int, deleted: bool = False) -> LedgerTransaction:  # type: ignore[no-untyped-def]
    account = db.scalar(select(Account)) or Account(name="Degiro")
    db.add(account)
    db.flush()
    tx = LedgerTransaction(
        account_id=account.id, instrument_id=instrument_id, type="buy", trade_date=date(2024, 1, 2),
        quantity=Decimal(3), price=Decimal(400),
        deleted_at=datetime.now(UTC) if deleted else None,
    )  # fmt: skip
    db.add(tx)
    db.commit()
    return tx


def test_deleting_a_held_instrument_shows_the_blocking_transactions(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    created = api.post("/api/v1/instruments", json=sxr8_body()).json()
    tx = add_transaction(db, created["id"])
    r = api.delete(f"/api/v1/instruments/{created['id']}")
    assert r.status_code == 409
    problem = r.json()
    assert "1 transaction still use it" in problem["detail"] and "archive" in problem["detail"]
    assert problem["blocking_total"] == 1
    assert problem["blocking_transactions"] == [
        {
            "id": tx.id,
            "type": "buy",
            "trade_date": "2024-01-02",
            "account": "Degiro",
            "quantity": "3",
        }
    ]
    assert api.get(f"/api/v1/instruments/{created['id']}").status_code == 200  # still there


def test_deleting_an_unused_instrument_and_adding_it_back_restores_its_history(
    api: TestClient, db
) -> None:  # type: ignore[no-untyped-def]
    created = api.post("/api/v1/instruments", json=sxr8_body()).json()
    add_transaction(db, created["id"], deleted=True)  # an undone entry does not block
    listing_id = created["listings"][0]["id"]
    db.add(
        PriceBar(
            listing_id=listing_id, date=date(2024, 1, 2), close=Decimal("454.19"), source="yahoo"
        )
    )
    db.commit()

    assert api.delete(f"/api/v1/instruments/{created['id']}").status_code == 204
    assert api.get(f"/api/v1/instruments/{created['id']}").status_code == 404
    assert api.get("/api/v1/instruments?status=all").json() == []

    again = api.post("/api/v1/instruments", json=sxr8_body(name="iShares S&P 500 (back)"))
    assert again.status_code == 201
    restored = again.json()
    assert restored["id"] == created["id"] and restored["name"] == "iShares S&P 500 (back)"
    assert restored["listings"][0]["id"] == listing_id
    assert restored["last_close"]["close"] == "454.19"  # the stored prices came back with it
    actions = [
        a.action for a in db.scalars(select(AuditLog).where(AuditLog.entity == "instrument"))
    ]
    assert actions == ["create", "delete", "restore"]
    assert db.query(Listing).count() == 1


def test_prices_endpoint_returns_stored_bars_in_order(api: TestClient, db) -> None:  # type: ignore[no-untyped-def]
    created = api.post("/api/v1/instruments", json=sxr8_body()).json()
    listing_id = created["listings"][0]["id"]
    for day, close in (
        (date(2024, 1, 3), "453.03"),
        (date(2024, 1, 2), "454.19"),
        (date(2024, 1, 4), "452.04"),
    ):
        db.add(PriceBar(listing_id=listing_id, date=day, close=Decimal(close), source="yahoo"))
    db.commit()
    rows = api.get(f"/api/v1/instruments/{created['id']}/prices").json()
    assert [(r["date"], r["close"]) for r in rows] == [
        ("2024-01-02", "454.19"), ("2024-01-03", "453.03"), ("2024-01-04", "452.04"),
    ]  # fmt: skip
    clipped = api.get(
        f"/api/v1/instruments/{created['id']}/prices?from=2024-01-03&to=2024-01-03"
    ).json()
    assert [r["date"] for r in clipped] == ["2024-01-03"]
    assert api.get("/api/v1/instruments/999/prices").status_code == 404
