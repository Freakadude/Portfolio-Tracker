from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import Column, Integer, MetaData, Table, select

from folio.db.engine import make_engine
from folio.db.types import DecimalText

metadata = MetaData()
amounts = Table(
    "amounts", metadata, Column("id", Integer, primary_key=True), Column("v", DecimalText)
)


@pytest.fixture(scope="module")
def engine(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    eng = make_engine(f"sqlite:///{tmp_path_factory.mktemp('db') / 't.db'}")
    metadata.create_all(eng)
    return eng


@given(
    st.decimals(
        allow_nan=False, allow_infinity=False, places=8, min_value=-(10**12), max_value=10**12
    )
)
def test_decimal_round_trip_is_exact(engine, value: Decimal) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as conn:
        pk = conn.execute(amounts.insert().values(v=value)).inserted_primary_key[0]
        got = conn.execute(select(amounts.c.v).where(amounts.c.id == pk)).scalar_one()
    assert got == value


def test_float_is_rejected(engine) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(Exception, match="floats are not allowed"), engine.begin() as conn:
        conn.execute(amounts.insert().values(v=0.1))


def test_non_finite_is_rejected(engine) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(Exception, match="finite"), engine.begin() as conn:
        conn.execute(amounts.insert().values(v=Decimal("NaN")))


def test_value_stored_as_text(engine) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as conn:
        conn.execute(amounts.insert().values(v=Decimal("1.10")))
        raw = conn.exec_driver_sql(
            "select typeof(v), v from amounts order by id desc limit 1"
        ).one()
    assert raw == ("text", "1.10")


def test_sqlite_folder_is_created(tmp_path) -> None:  # type: ignore[no-untyped-def]
    target = tmp_path / "nested" / "dir" / "folio.db"
    make_engine(f"sqlite:///{target}").connect().close()
    assert target.exists()
