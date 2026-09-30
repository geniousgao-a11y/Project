from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..rebalance import Order


@dataclass
class Account:
    cash: float
    positions: dict[str, float] = field(default_factory=dict)  # symbol -> qty
    equity: float = 0.0


@dataclass
class Fill:
    symbol: str
    side: str
    qty: float
    price: float | None  # None when the broker hasn't filled yet (e.g. queued)
    status: str = "filled"
    broker_id: str | None = None


class Broker(ABC):
    is_live: bool = False

    @abstractmethod
    def account(self, prices: dict[str, float]) -> Account:
        """Current cash, positions and equity (valued at ``prices`` if needed)."""

    @abstractmethod
    def submit(self, orders: list[Order], prices: dict[str, float]) -> list[Fill]:
        """Execute orders, sells before buys."""

    def market_open(self) -> bool:
        return True
