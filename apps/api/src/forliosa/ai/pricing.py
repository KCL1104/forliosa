"""Token usage numbers and a cost estimate (USD) per model call.

Prices per million tokens as published on 2026-11-12 (``docs/research/claude-platform-fit.md``); re-check the
pricing page before relying on the numbers. Cache reads and 5-minute cache writes are multiples of the input
price. Claude Haiku 5.5 has a second rate card above 100K prompt tokens. Web search is US$10 per 1,000
searches; web fetch has no charge beyond tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

MTOK = Decimal(1_000_000)
WEB_SEARCH_USD = Decimal("0.01")
LONG_PROMPT_TOKENS = 100_000
CACHE_WRITE_MULT = Decimal("1.25")


@dataclass(frozen=True)
class Price:
    input: Decimal
    output: Decimal
    cache_read_mult: Decimal = Decimal("0.1")
    long_input: Decimal | None = None  # prompts over LONG_PROMPT_TOKENS
    long_output: Decimal | None = None


PRICES: dict[str, Price] = {
    "claude-haiku-5-5": Price(Decimal("0.10"), Decimal("0.50"), Decimal("0.1"), Decimal("0.50"), Decimal("2.50")),
    "claude-sonnet-5-5": Price(Decimal("2"), Decimal("10"), Decimal("0.05")),
    "claude-opus-5-5": Price(Decimal("4"), Decimal("20"), Decimal("0.05")),
}
DEFAULT_PRICE = PRICES["claude-haiku-5-5"]


@dataclass
class CallUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    web_search_requests: int = 0
    web_fetch_requests: int = 0

    @classmethod
    def from_sdk(cls, usage: Any) -> CallUsage:
        if usage is None:
            return cls()
        stu = getattr(usage, "server_tool_use", None)
        return cls(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            web_search_requests=(getattr(stu, "web_search_requests", 0) or 0) if stu else 0,
            web_fetch_requests=(getattr(stu, "web_fetch_requests", 0) or 0) if stu else 0,
        )

    def add(self, other: CallUsage) -> None:
        for f in self.__dataclass_fields__:
            setattr(self, f, getattr(self, f) + getattr(other, f))

    @property
    def prompt_tokens(self) -> int:
        """Whole prompt size: uncached input + cache writes + cache reads."""
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens

    def as_dict(self) -> dict[str, int]:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}


def price_of(model: str) -> Price:
    return PRICES.get(model, DEFAULT_PRICE)


def estimate_cost(model: str, u: CallUsage) -> Decimal:
    p = price_of(model)
    long = u.prompt_tokens > LONG_PROMPT_TOKENS and p.long_input is not None
    inp = p.long_input if long and p.long_input is not None else p.input
    out = p.long_output if long and p.long_output is not None else p.output
    cost = (Decimal(u.input_tokens) * inp
            + Decimal(u.cache_creation_input_tokens) * inp * CACHE_WRITE_MULT
            + Decimal(u.cache_read_input_tokens) * inp * p.cache_read_mult
            + Decimal(u.output_tokens) * out) / MTOK
    cost += WEB_SEARCH_USD * u.web_search_requests
    return cost.quantize(Decimal("0.000001"))


def billable_tokens(u: CallUsage) -> int:
    """What the monthly token budget counts: everything processed at full (or higher) price, plus cache
    reads at one tenth (they cost about a tenth)."""
    return u.input_tokens + u.cache_creation_input_tokens + u.output_tokens + -(-u.cache_read_input_tokens // 10)
