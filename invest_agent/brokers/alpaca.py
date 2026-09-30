"""Alpaca (https://alpaca.markets) broker via its REST API.

Commission-free US stocks/ETFs, fractional shares, and a free paper-trading
account with the same API. Keys come from the environment:

    ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY
"""

from __future__ import annotations

import os
import time

import requests

from ..rebalance import Order
from .base import Account, Broker, Fill

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"


class AlpacaBroker(Broker):
    def __init__(self, live: bool = False, key_id: str | None = None, secret: str | None = None,
                 session: requests.Session | None = None):
        self.is_live = live
        self.base_url = LIVE_URL if live else PAPER_URL
        key_id = key_id or os.environ.get("ALPACA_API_KEY_ID")
        secret = secret or os.environ.get("ALPACA_API_SECRET_KEY")
        if not key_id or not secret:
            raise RuntimeError("Set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY (see .env.example)")
        self.http = session or requests.Session()
        self.http.headers.update({"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret})

    def _req(self, method: str, path: str, **kw):
        r = self.http.request(method, self.base_url + path, timeout=30, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"Alpaca {method} {path} failed [{r.status_code}]: {r.text}")
        return r.json()

    def market_open(self) -> bool:
        return bool(self._req("GET", "/v2/clock")["is_open"])

    def account(self, prices=None):
        acct = self._req("GET", "/v2/account")
        positions = {p["symbol"]: float(p["qty"]) for p in self._req("GET", "/v2/positions")}
        return Account(cash=float(acct["cash"]), positions=positions, equity=float(acct["equity"]))

    def _wait(self, order_id: str, timeout: float = 60) -> dict:
        deadline = time.time() + timeout
        while True:
            o = self._req("GET", f"/v2/orders/{order_id}")
            if o["status"] in ("filled", "canceled", "rejected", "expired") or time.time() > deadline:
                return o
            time.sleep(1)

    def submit(self, orders, prices):
        fills = []
        for o in sorted(orders, key=lambda o: o.side != "sell"):
            body = {"symbol": o.symbol, "qty": str(o.qty), "side": o.side,
                    "type": "market", "time_in_force": "day"}
            placed = self._req("POST", "/v2/orders", json=body)
            # Wait for sells to fill so their cash is available for buys.
            final = self._wait(placed["id"]) if o.side == "sell" else placed
            px = final.get("filled_avg_price")
            fills.append(Fill(o.symbol, o.side, float(final.get("filled_qty") or 0) or o.qty,
                              float(px) if px else None, status=final["status"], broker_id=placed["id"]))
        return fills
