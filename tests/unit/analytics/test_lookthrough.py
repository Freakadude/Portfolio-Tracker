"""Look-through allocation (FR-PF-05): a company held directly and inside two ETFs shows as one
exposure with its breakdown, and the exposures always add up to the value that was opened."""

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from folio.analytics.lookthrough import (
    DIMENSIONS,
    Holdings,
    Wrapper,
    aggregate,
    company_key,
    concentration,
    country_name,
    expand,
    sector_name,
)
from folio.lookthrough.parse import Constituent

D = Decimal


def c(
    name: str,
    weight: str,
    isin: str | None = None,
    sector: str | None = None,
    country: str | None = None,
) -> Constituent:
    return Constituent(name=name, weight_pct=D(weight), isin=isin, sector=sector, country=country)


# ASML is held directly (5 000), inside a world ETF (10 000, 4 %) and a tech ETF (20 000, 10 %)
DIRECT = Wrapper(1, "ASML Holding", "NL0010273215", D(5000), "Technology", "NL", "EUR")
WORLD = Wrapper(2, "World ETF", "IE0000000001", D(10000))
TECH = Wrapper(3, "Tech ETF", "IE0000000002", D(20000))
HOLDINGS = {
    2: Holdings(
        D(100),
        [
            c("APPLE INC", "6", "US0378331005", "Information Technology", "United States"),
            c("ASML HOLDING NV", "4", "NL0010273215", "Information Technology", "Netherlands"),
            c("OTHER CO", "90", None, "Financials", "Germany"),
        ],
    ),
    3: Holdings(
        D(95),
        [
            c("ASML Holding N.V.", "10", "NL0010273215", "Technology", "NL"),
            c("CHIP MAKER", "85", None, "Technology", "Taiwan"),
        ],
    ),
}


def test_a_company_held_directly_and_inside_two_etfs_is_one_exposure() -> None:
    exposures = aggregate(expand([DIRECT, WORLD, TECH], HOLDINGS), "company")
    asml = next(e for e in exposures if e.key == "NL0010273215")
    assert asml.value_eur == D(5000) + D(400) + D(2000)  # direct, 4 % of 10 000, 10 % of 20 000
    assert asml.label == "ASML Holding"  # the name of the owner's own holding
    assert abs(asml.weight - D(7400) / D(35000)) < D("1e-20")
    assert [(p.source, p.kind, p.value_eur, p.weight_pct) for p in asml.parts] == [
        ("ASML Holding", "direct", D(5000), None),
        ("Tech ETF", "look_through", D(2000), D(10)),
        ("World ETF", "look_through", D(400), D(4)),
    ]


def test_without_an_isin_companies_are_matched_by_a_normalised_name() -> None:
    assert company_key("ASML Holding N.V.", None) == company_key("ASML HOLDING NV", None) == "asml"
    assert company_key("Alphabet Inc Class A", None) == company_key("ALPHABET INC. CLASS A", None)
    assert company_key("Apple Inc", "us0378331005") == "US0378331005"
    wrappers = [Wrapper(1, "ASML Holding", None, D(1000)), Wrapper(2, "ETF", None, D(2000))]
    merged = aggregate(
        expand(wrappers, {2: Holdings(D(100), [c("ASML HOLDING NV", "50")])}), "company"
    )
    assert [(e.label, e.value_eur, e.other) for e in merged] == [
        ("ASML Holding", D(2000), False),  # 1 000 direct + half of the ETF's 2 000
        ("Other holdings of ETF", D(1000), True),  # the half of the ETF the file did not name
    ]


def test_what_the_file_does_not_cover_stays_as_other_holdings_and_is_no_company() -> None:
    exposures = aggregate(expand([TECH], HOLDINGS), "company")
    other = next(e for e in exposures if e.other)
    assert (other.label, other.value_eur) == (
        "Other holdings of Tech ETF",
        D(1000),
    )  # 5 % of 20 000
    assert other not in concentration(exposures)
    assert [e.label for e in concentration(exposures)] == ["CHIP MAKER", "ASML Holding N.V."]


def test_a_file_adding_up_to_more_than_a_hundred_percent_is_scaled_not_invented() -> None:
    holdings = {2: Holdings(D(102), [c("A", "51"), c("B", "51")])}
    exposures = aggregate(expand([WORLD], holdings), "company")
    assert sum(e.value_eur for e in exposures) == pytest.approx(D(10000), abs=D("0.000001"))
    assert not any(e.other for e in exposures)


def test_an_etf_without_holdings_stays_itself_and_is_no_company() -> None:
    fund = Wrapper(2, "World ETF", "IE0000000001", D(10000), is_fund=True)
    exposures = aggregate(expand([fund], {}), "company")
    assert [(e.label, e.value_eur, e.parts[0].kind, e.other) for e in exposures] == [
        ("World ETF", D(10000), "fund", True)
    ]
    assert concentration(exposures) == []  # "World ETF is 100 % of the portfolio" is no finding


def test_sectors_countries_and_currencies_add_up_across_spellings() -> None:
    atoms = expand([DIRECT, WORLD, TECH], HOLDINGS)
    sectors = {e.label: e.value_eur for e in aggregate(atoms, "sector")}
    assert sectors["Information Technology"] == D(25000)  # 5 000 direct, 1 000 and 19 000 in ETFs
    countries = {e.label: e.value_eur for e in aggregate(atoms, "country")}
    assert countries["Netherlands"] == D(5000) + D(400) + D(2000)  # "NL" and "Netherlands"
    currencies = {e.label: e.value_eur for e in aggregate(atoms, "currency")}
    assert currencies["EUR"] == D(5000)  # only the direct holding states one
    assert currencies["Unclassified"] == D(30000)
    by_sector = aggregate(atoms, "sector")[0]
    assert {p.source for p in by_sector.parts} == {"ASML Holding", "World ETF", "Tech ETF"}


def test_names_are_normalised_in_one_place() -> None:
    assert (country_name("USA"), country_name("us"), country_name("-"), country_name(None)) == (
        "United States",
        "United States",
        None,
        None,
    )
    assert country_name("Chile") == "Chile"  # unknown names are kept as given
    assert sector_name("Financial Services") == sector_name("Financials") == "Financials"


def test_an_unknown_dimension_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown dimension"):
        aggregate([], "colour")


names = st.sampled_from(["Alpha", "Beta", "Gamma", "Delta Corp", "Delta Inc", "Epsilon"])
sectors = st.sampled_from([None, "Technology", "Information Technology", "Energy", "Utilities"])
countries = st.sampled_from([None, "US", "United States", "NL", "Germany"])


@st.composite
def portfolios(draw):  # type: ignore[no-untyped-def]
    wrappers, holdings = [], {}
    for n in range(draw(st.integers(1, 4))):
        wrappers.append(
            Wrapper(
                n,
                f"Position {n}",
                None,
                D(draw(st.integers(1, 1_000_000))),
                draw(sectors),
                draw(countries),
                draw(st.sampled_from([None, "EUR", "USD"])),
            )
        )
        if draw(st.booleans()):
            weights = draw(st.lists(st.integers(1, 30), min_size=1, max_size=6))
            holdings[n] = Holdings(
                D(sum(weights)),
                [
                    Constituent(draw(names), D(w), None, draw(sectors), draw(countries))
                    for w in weights
                ],
            )
    return wrappers, holdings


@settings(max_examples=150, deadline=None)
@given(portfolios())
def test_the_exposures_always_add_up_to_the_value_of_the_positions(case) -> None:  # type: ignore[no-untyped-def]
    wrappers, holdings = case
    total = sum((w.value_eur for w in wrappers), D(0))
    atoms = expand(wrappers, holdings)
    for dimension in DIMENSIONS:
        exposures = aggregate(atoms, dimension)
        assert abs(sum(e.value_eur for e in exposures) - total) < D("0.00001")
        assert abs(sum(e.weight for e in exposures) - 1) < D("0.0000001")
        assert all(e.value_eur > 0 for e in exposures)
        assert [e.value_eur for e in exposures] == sorted(
            (e.value_eur for e in exposures), reverse=True
        )
        for e in exposures:  # the breakdown explains every exposure
            assert abs(sum(p.value_eur for p in e.parts) - e.value_eur) < D("0.00001")
