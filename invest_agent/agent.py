"""The trading loop: data -> strategy -> risk -> orders -> broker -> journal."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from .brokers import Broker, Fill
from .config import Config
from .data import DataProvider
from .rebalance import Order, plan_orders
from .risk import RiskManager
from .strategies import Strategy


def period_key(d: date, frequency: str) -> str:
    if frequency == "daily":
        return d.isoformat()
    if frequency == "weekly":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    return f"{d.year}-{d.month:02d}"


def universe_symbols(cfg: Config, strategy: Strategy) -> list[str]:
    symbols = list(cfg.universe)
    safe = getattr(strategy, "safe_asset", None)
    if safe and safe not in symbols:
        symbols.append(safe)
    return symbols


@dataclass
class RunReport:
    timestamp: str
    as_of: str
    equity: float
    cash: float
    action: str  # "rebalanced", "dry_run", "skipped", "halted"
    target_weights: dict[str, float] = field(default_factory=dict)
    orders: list[dict] = field(default_factory=list)
    fills: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"[{self.as_of}] equity=${self.equity:,.2f} cash=${self.cash:,.2f} action={self.action}"]
        if self.target_weights:
            tw = ", ".join(f"{s} {w:.1%}" for s, w in sorted(self.target_weights.items(), key=lambda x: -x[1]))
            lines.append(f"  targets: {tw}")
        for o in self.orders:
            lines.append(f"  order: {o['side']:4} {o['qty']:.4f} {o['symbol']} (~${o['qty'] * o['est_price']:,.2f})")
        lines += [f"  note: {n}" for n in self.notes]
        return "\n".join(lines)


class AgentState:
    """Small persistent state: peak equity, halt flag, last rebalance period."""

    def __init__(self, path: Path):
        self.path = path
        data = json.loads(path.read_text()) if path.exists() else {}
        self.peak_equity: float = data.get("peak_equity", 0.0)
        self.halted: bool = data.get("halted", False)
        self.last_rebalance: str | None = data.get("last_rebalance")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"peak_equity": self.peak_equity, "halted": self.halted,
                                         "last_rebalance": self.last_rebalance}, indent=2))


class InvestmentAgent:
    def __init__(self, cfg: Config, broker: Broker, data: DataProvider, strategy: Strategy):
        self.cfg = cfg
        self.broker = broker
        self.data = data
        self.strategy = strategy
        self.risk = RiskManager(cfg.risk)
        state_dir = Path(cfg.state_dir)
        self.state = AgentState(state_dir / "agent_state.json")
        self.journal_path = state_dir / "journal.jsonl"

    def load_prices(self, as_of: date) -> pd.DataFrame:
        calendar_days = int(self.strategy.lookback_days * 1.5) + 15
        start = (pd.Timestamp(as_of) - pd.Timedelta(days=calendar_days)).date()
        prices = self.data.history(universe_symbols(self.cfg, self.strategy), start, as_of)
        if len(prices) < self.strategy.lookback_days:
            raise ValueError(f"Need {self.strategy.lookback_days} days of history, got {len(prices)}")
        return prices

    def run_once(self, as_of: date | None = None, dry_run: bool = False, force: bool = False) -> RunReport:
        as_of = as_of or date.today()
        prices = self.load_prices(as_of)
        latest = prices.iloc[-1].to_dict()
        acct = self.broker.account(latest)
        self.state.peak_equity = max(self.state.peak_equity, acct.equity)
        report = RunReport(timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           as_of=str(prices.index[-1].date()), equity=acct.equity, cash=acct.cash, action="skipped")

        if self.broker.is_live:
            report.notes.append("LIVE account: real money")
        if self.state.halted:
            report.action = "halted"
            report.notes.append("Agent is halted after hitting the drawdown limit. Run `invest-agent reset-halt` to resume.")
            return self._finish(report, dry_run)

        key = period_key(as_of, self.cfg.rebalance)
        if not force and self.state.last_rebalance == key:
            report.notes.append(f"Already rebalanced for period {key} ({self.cfg.rebalance}); use --force to override.")
            return self._finish(report, dry_run)

        decision = self.risk.apply(self.strategy.target_weights(prices), acct.equity, self.state.peak_equity)
        report.target_weights = decision.weights
        report.notes += decision.notes

        # Price any held symbol outside the universe too so it can be sold.
        missing = [s for s in acct.positions if s not in latest]
        if missing:
            extra = self.data.history(missing, (pd.Timestamp(as_of) - pd.Timedelta(days=10)).date(), as_of)
            latest.update(extra.iloc[-1].to_dict())

        orders = plan_orders(acct.positions, latest, acct.cash, decision.weights,
                             self.cfg.risk.min_trade_value, self.cfg.risk.rebalance_threshold,
                             self.cfg.fractional_shares)
        report.orders = [asdict(o) for o in orders]

        if dry_run:
            report.action = "dry_run"
            return self._finish(report, dry_run)

        fills: list[Fill] = self.broker.submit(orders, latest) if orders else []
        report.fills = [asdict(f) for f in fills]
        report.action = "rebalanced"
        self.state.last_rebalance = key
        if decision.halt:
            self.state.halted = True
            report.action = "halted"
        return self._finish(report, dry_run)

    def _finish(self, report: RunReport, dry_run: bool) -> RunReport:
        if not dry_run:
            self.state.save()
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            with self.journal_path.open("a") as f:
                f.write(json.dumps(asdict(report)) + "\n")
        return report


__all__ = ["InvestmentAgent", "RunReport", "Order", "period_key", "universe_symbols"]
