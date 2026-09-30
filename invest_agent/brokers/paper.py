"""Local simulated broker. No money involved; state is a JSON file."""

from __future__ import annotations

import json
from pathlib import Path

from ..rebalance import Order
from .base import Account, Broker, Fill


class PaperBroker(Broker):
    is_live = False

    def __init__(self, starting_cash: float = 10_000.0, state_path: str | Path | None = None,
                 commission: float = 0.0, slippage_bps: float = 5.0):
        self.state_path = Path(state_path) if state_path else None
        self.commission = commission
        self.slippage = slippage_bps / 10_000
        self.cash = starting_cash
        self.positions: dict[str, float] = {}
        if self.state_path and self.state_path.exists():
            state = json.loads(self.state_path.read_text())
            self.cash = state["cash"]
            self.positions = state["positions"]

    def _save(self) -> None:
        if self.state_path:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps({"cash": self.cash, "positions": self.positions}, indent=2))

    def account(self, prices):
        equity = self.cash + sum(q * prices[s] for s, q in self.positions.items())
        return Account(cash=self.cash, positions=dict(self.positions), equity=equity)

    def submit(self, orders, prices):
        fills = []
        for o in sorted(orders, key=lambda o: o.side != "sell"):
            base = prices[o.symbol]
            if o.side == "sell":
                qty = min(o.qty, self.positions.get(o.symbol, 0.0))
                px = base * (1 - self.slippage)
                self.cash += qty * px - self.commission
                remaining = self.positions.get(o.symbol, 0.0) - qty
                if remaining <= 1e-9:
                    self.positions.pop(o.symbol, None)
                else:
                    self.positions[o.symbol] = remaining
            else:
                px = base * (1 + self.slippage)
                qty = min(o.qty, max(self.cash - self.commission, 0) / px)
                if qty <= 0:
                    fills.append(Fill(o.symbol, o.side, 0, None, status="rejected: insufficient cash"))
                    continue
                self.cash -= qty * px + self.commission
                self.positions[o.symbol] = self.positions.get(o.symbol, 0.0) + qty
            fills.append(Fill(o.symbol, o.side, qty, px))
        self._save()
        return fills
