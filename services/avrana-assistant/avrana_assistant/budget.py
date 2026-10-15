"""Token and cost ceilings. Fails closed: with no valid configuration nothing is allowed.

Prices and ceilings are configuration supplied by the owner (integer micro-units of whatever currency is
used; the code does not know or assume any provider's prices or model identifiers). The price table is
keyed by an opaque `model_label`.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Callable, Mapping


class BudgetError(Exception):
    pass


class ConfigError(BudgetError):
    pass


class BudgetDenied(BudgetError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Price:
    input_per_1k_micro: int
    output_per_1k_micro: int


_REQUIRED = ("per_request_max_tokens", "per_request_max_cost_micro", "member_daily_tokens",
             "member_daily_cost_micro", "member_daily_requests", "global_daily_tokens", "global_daily_cost_micro")


@dataclass(frozen=True)
class BudgetConfig:
    prices: Mapping[str, Price]
    per_request_max_tokens: int
    per_request_max_cost_micro: int
    member_daily_tokens: int
    member_daily_cost_micro: int
    member_daily_requests: int
    global_daily_tokens: int
    global_daily_cost_micro: int

    @classmethod
    def from_mapping(cls, data: Mapping) -> "BudgetConfig":
        if not isinstance(data, Mapping):
            raise ConfigError("budget config must be a mapping")
        for k in _REQUIRED:
            v = data.get(k)
            if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
                raise ConfigError(f"missing or invalid {k}")
        prices_raw = data.get("prices")
        if not isinstance(prices_raw, Mapping) or not prices_raw:
            raise ConfigError("missing price table")
        prices = {}
        for label, p in prices_raw.items():
            try:
                pi, po = int(p["input_per_1k_micro"]), int(p["output_per_1k_micro"])
            except (KeyError, TypeError, ValueError):
                raise ConfigError(f"bad price entry {label!r}") from None
            if pi < 0 or po < 0:
                raise ConfigError(f"negative price {label!r}")
            prices[str(label)] = Price(pi, po)
        return cls(prices, *(data[k] for k in _REQUIRED))


@dataclass
class Reservation:
    member: str
    day: _dt.date
    tokens: int
    cost: int
    model_label: str
    settled: bool = False


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


class BudgetGuard:
    def __init__(self, config: BudgetConfig | None, clock: Callable[[], _dt.datetime] | None = None):
        self.config = config
        self.clock = clock or (lambda: _dt.datetime.now(_dt.timezone.utc))
        self._member: dict[tuple[str, _dt.date], dict] = {}
        self._global: dict[_dt.date, dict] = {}

    @staticmethod
    def _bucket(table, key):
        return table.setdefault(key, {"tokens": 0, "cost": 0, "requests": 0})

    def _cost(self, label: str, in_tok: int, out_tok: int) -> int:
        p = self.config.prices[label]
        return _ceil_div(in_tok * p.input_per_1k_micro, 1000) + _ceil_div(out_tok * p.output_per_1k_micro, 1000)

    def reserve(self, member: str, model_label: str, input_tokens: int, max_output_tokens: int) -> Reservation:
        """Worst-case reservation (all output tokens used). Raises BudgetDenied; never partially applies."""
        cfg = self.config
        if cfg is None:
            raise BudgetDenied("budget_not_configured")
        if model_label not in cfg.prices:
            raise BudgetDenied("no_price_for_model_label")
        if input_tokens < 0 or max_output_tokens <= 0:
            raise BudgetDenied("invalid_token_counts")
        tokens = input_tokens + max_output_tokens
        cost = self._cost(model_label, input_tokens, max_output_tokens)
        if tokens > cfg.per_request_max_tokens:
            raise BudgetDenied("per_request_tokens")
        if cost > cfg.per_request_max_cost_micro:
            raise BudgetDenied("per_request_cost")
        day = self.clock().astimezone(_dt.timezone.utc).date()
        m = self._bucket(self._member, (member, day))
        g = self._bucket(self._global, day)
        if m["requests"] + 1 > cfg.member_daily_requests:
            raise BudgetDenied("member_daily_requests")
        if m["tokens"] + tokens > cfg.member_daily_tokens:
            raise BudgetDenied("member_daily_tokens")
        if m["cost"] + cost > cfg.member_daily_cost_micro:
            raise BudgetDenied("member_daily_cost")
        if g["tokens"] + tokens > cfg.global_daily_tokens:
            raise BudgetDenied("global_daily_tokens")
        if g["cost"] + cost > cfg.global_daily_cost_micro:
            raise BudgetDenied("global_daily_cost")
        for b in (m, g):
            b["tokens"] += tokens
            b["cost"] += cost
        m["requests"] += 1
        g["requests"] += 1
        return Reservation(member, day, tokens, cost, model_label)

    def settle(self, r: Reservation, input_tokens: int, output_tokens: int) -> None:
        """Replace the worst-case reservation with actual usage (never more than the reservation)."""
        if r.settled:
            return
        actual_tokens = min(input_tokens + output_tokens, r.tokens)
        actual_cost = min(self._cost(r.model_label, input_tokens, output_tokens), r.cost)
        for b in (self._bucket(self._member, (r.member, r.day)), self._bucket(self._global, r.day)):
            b["tokens"] += actual_tokens - r.tokens
            b["cost"] += actual_cost - r.cost
        r.settled = True

    def release(self, r: Reservation) -> None:
        """Provider was never called (for example the egress filter blocked): return the reservation."""
        if r.settled:
            return
        self.settle(r, 0, 0)
        for b in (self._bucket(self._member, (r.member, r.day)), self._bucket(self._global, r.day)):
            b["requests"] -= 1

    def usage(self, member: str) -> dict:
        day = self.clock().astimezone(_dt.timezone.utc).date()
        return {"member": dict(self._bucket(self._member, (member, day))), "global": dict(self._bucket(self._global, day))}
