"""What an LLM call costs (FR-AG-04).

Cost is computed from the usage the API reports times a price table in the settings (US dollars
per million tokens), plus web searches counted separately, and converted to euro at the latest
ECB rate. A worst case is computed before a call so the budget can refuse it in advance.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from folio.settings_schema import ModelPrice

MILLION = Decimal(1_000_000)
THOUSAND = Decimal(1000)
EUR_QUANTUM = Decimal("0.000001")
CHARS_PER_TOKEN = 3  # a cautious estimate: real text averages about four characters per token


@dataclass(frozen=True)
class Usage:
    """Tokens and searches of one call, or the sum of several."""

    input_tokens: int = 0  # not counting cached tokens
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_searches: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
            self.web_searches + other.web_searches,
        )

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )


def cost_usd(usage: Usage, price: ModelPrice, web_search_usd_per_1000: Decimal) -> Decimal:
    tokens = (
        Decimal(usage.input_tokens) * price.input_usd
        + Decimal(usage.output_tokens) * price.output_usd
        + Decimal(usage.cache_write_tokens) * price.cache_write_usd
        + Decimal(usage.cache_read_tokens) * price.cache_read_usd
    ) / MILLION
    return tokens + Decimal(usage.web_searches) * web_search_usd_per_1000 / THOUSAND


def to_eur(usd: Decimal, usd_per_eur: Decimal) -> Decimal:
    return (usd / usd_per_eur).quantize(EUR_QUANTUM, ROUND_HALF_UP)


def estimate_input_tokens(characters: int) -> int:
    return -(-characters // CHARS_PER_TOKEN)  # rounded up


def worst_case_usd(
    price: ModelPrice,
    input_tokens: int,
    max_output_tokens: int,
    max_searches: int,
    web_search_usd_per_1000: Decimal,
) -> Decimal:
    """The most a call can cost: all input uncached at the full price, the whole output allowance
    used, every search made."""
    return cost_usd(
        Usage(
            input_tokens=input_tokens, output_tokens=max_output_tokens, web_searches=max_searches
        ),
        price,
        web_search_usd_per_1000,
    )
