from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

STRATEGIES: dict[str, type["Strategy"]] = {}


def register(cls: type["Strategy"]) -> type["Strategy"]:
    STRATEGIES[cls.name] = cls
    return cls


def make_strategy(name: str, **params) -> "Strategy":
    if name not in STRATEGIES:
        raise ValueError(f"Unknown strategy {name!r}. Available: {sorted(STRATEGIES)}")
    return STRATEGIES[name](**params)


class Strategy(ABC):
    """A strategy turns price history into target portfolio weights.

    To add a new strategy: subclass this, set ``name``, implement
    ``target_weights``, decorate with ``@register`` and import the module in
    ``strategies/__init__.py``. It then works with ``run`` and ``backtest``.
    """

    name: str = ""

    @property
    @abstractmethod
    def lookback_days(self) -> int:
        """Trading days of history needed before the strategy can decide."""

    @abstractmethod
    def target_weights(self, prices: pd.DataFrame) -> dict[str, float]:
        """Return {symbol: weight}. Weights should be >= 0 and sum to <= 1;
        anything unallocated stays in cash. ``prices`` ends at "today" --
        never peek at later rows."""


def inverse_vol_weights(prices: pd.DataFrame, symbols: list[str], window: int = 63) -> dict[str, float]:
    if not symbols:
        return {}
    vol = prices[symbols].pct_change().iloc[-window:].std()
    inv = 1 / vol.replace(0, vol[vol > 0].min() if (vol > 0).any() else 1)
    inv = inv / inv.sum()
    return inv.to_dict()
