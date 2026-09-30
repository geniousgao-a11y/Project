"""Turn target weights into concrete orders."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Order:
    symbol: str
    side: str  # "buy" or "sell"
    qty: float
    est_price: float

    @property
    def est_value(self) -> float:
        return self.qty * self.est_price


def plan_orders(
    positions: dict[str, float],
    prices: dict[str, float],
    cash: float,
    target_weights: dict[str, float],
    min_trade_value: float = 25.0,
    rebalance_threshold: float = 0.02,
    fractional: bool = True,
) -> list[Order]:
    """Sells come first (they fund the buys). Buys are scaled down if cash
    after sells can't cover them. Positions whose target is zero are always
    fully exited, regardless of thresholds."""
    equity = cash + sum(q * prices[s] for s, q in positions.items())
    if equity <= 0:
        return []

    def round_qty(q: float) -> float:
        return math.floor(q * 1e6) / 1e6 if fractional else float(math.floor(q))

    sells: list[Order] = []
    buys: list[Order] = []
    for sym in sorted(set(positions) | set(target_weights)):
        price = prices[sym]
        cur_qty = positions.get(sym, 0.0)
        target_w = target_weights.get(sym, 0.0)
        diff_value = target_w * equity - cur_qty * price

        if target_w == 0 and cur_qty > 0:
            sells.append(Order(sym, "sell", cur_qty, price))
            continue
        if abs(diff_value) / equity < rebalance_threshold or abs(diff_value) < min_trade_value:
            continue
        qty = round_qty(abs(diff_value) / price)
        if qty <= 0:
            continue
        if diff_value < 0:
            sells.append(Order(sym, "sell", min(qty, cur_qty), price))
        else:
            buys.append(Order(sym, "buy", qty, price))

    available = cash + sum(o.est_value for o in sells)
    needed = sum(o.est_value for o in buys)
    if needed > available and needed > 0:
        scale = available / needed * 0.999  # headroom for slippage
        buys = [Order(o.symbol, "buy", round_qty(o.qty * scale), o.est_price) for o in buys]
        buys = [o for o in buys if o.qty > 0 and o.est_value >= min_trade_value]
    return sells + buys
