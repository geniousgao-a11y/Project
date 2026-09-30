from __future__ import annotations

import pandas as pd

from .base import Strategy, inverse_vol_weights, register


@register
class DualMomentum(Strategy):
    """Rotate into the strongest assets, but only while they're trending up.

    * Relative momentum: rank the universe by a blend of 3/6/12-month returns
      and pick the top ``top_n``.
    * Absolute momentum: a pick with a negative score is replaced by
      ``safe_asset`` (e.g. a T-bill ETF like "BIL") or held as cash.

    A well-known, simple approach that historically cut deep drawdowns.
    That's no guarantee it'll keep working.
    """

    name = "dual_momentum"

    def __init__(self, top_n: int = 3, lookbacks=(63, 126, 252), safe_asset: str | None = None,
                 weighting: str = "equal"):
        if weighting not in ("equal", "inverse_vol"):
            raise ValueError("weighting must be 'equal' or 'inverse_vol'")
        self.top_n = top_n
        self.lookbacks = tuple(lookbacks)
        self.safe_asset = safe_asset.upper() if safe_asset else None
        self.weighting = weighting

    @property
    def lookback_days(self) -> int:
        return max(self.lookbacks) + 1

    def scores(self, prices: pd.DataFrame) -> pd.Series:
        rets = [prices.iloc[-1] / prices.iloc[-1 - lb] - 1 for lb in self.lookbacks]
        return sum(rets) / len(rets)

    def target_weights(self, prices):
        risky = [c for c in prices.columns if c != self.safe_asset]
        scores = self.scores(prices[risky]).sort_values(ascending=False)
        picks = list(scores.index[: self.top_n])
        winners = [s for s in picks if scores[s] > 0]
        slot = 1.0 / max(len(picks), 1)

        if self.weighting == "inverse_vol" and winners:
            iv = inverse_vol_weights(prices, winners)
            weights = {s: iv[s] * slot * len(winners) for s in winners}
        else:
            weights = {s: slot for s in winners}

        leftover = 1.0 - sum(weights.values())
        if leftover > 1e-9 and self.safe_asset and self.safe_asset in prices.columns:
            weights[self.safe_asset] = weights.get(self.safe_asset, 0) + leftover
        return weights
