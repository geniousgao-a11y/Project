from __future__ import annotations

from .base import Strategy, inverse_vol_weights, register


@register
class SmaTrend(Strategy):
    """Hold each asset only while its price is above its moving average.

    Every asset gets an equal (or inverse-volatility) slice; assets below
    their ``window``-day SMA have their slice parked in cash.
    """

    name = "sma_trend"

    def __init__(self, window: int = 200, weighting: str = "equal"):
        if weighting not in ("equal", "inverse_vol"):
            raise ValueError("weighting must be 'equal' or 'inverse_vol'")
        self.window = window
        self.weighting = weighting

    @property
    def lookback_days(self) -> int:
        return self.window + 1

    def target_weights(self, prices):
        symbols = list(prices.columns)
        if self.weighting == "inverse_vol":
            base = inverse_vol_weights(prices, symbols)
        else:
            base = {s: 1 / len(symbols) for s in symbols}
        sma = prices.iloc[-self.window:].mean()
        last = prices.iloc[-1]
        return {s: w for s, w in base.items() if last[s] > sma[s]}
