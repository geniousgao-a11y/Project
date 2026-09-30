"""Replay a strategy over history, using the same risk + rebalancing code as live runs."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .brokers.paper import PaperBroker
from .config import Config
from .agent import period_key
from .rebalance import plan_orders
from .risk import RiskManager
from .strategies import Strategy


@dataclass
class BacktestResult:
    equity: pd.Series
    benchmark: pd.Series | None
    trades: int
    halted_on: str | None

    def stats(self, series: pd.Series | None = None) -> dict[str, float]:
        s = self.equity if series is None else series
        rets = s.pct_change().dropna()
        years = max((s.index[-1] - s.index[0]).days / 365.25, 1e-9)
        cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1
        vol = rets.std() * np.sqrt(252)
        sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0.0
        max_dd = (s / s.cummax() - 1).min()
        return {"total_return": s.iloc[-1] / s.iloc[0] - 1, "cagr": cagr, "volatility": vol,
                "sharpe": sharpe, "max_drawdown": max_dd, "final_equity": s.iloc[-1]}

    def report(self) -> str:
        cols = {"Strategy": self.stats()}
        if self.benchmark is not None:
            cols[f"Buy&hold {self.benchmark.name}"] = self.stats(self.benchmark)
        lines = [f"Period: {self.equity.index[0].date()} -> {self.equity.index[-1].date()}   trades: {self.trades}"]
        header = f"{'':16}" + "".join(f"{k:>20}" for k in cols)
        lines.append(header)
        for key, fmt in [("total_return", "{:.1%}"), ("cagr", "{:.1%}"), ("volatility", "{:.1%}"),
                         ("sharpe", "{:.2f}"), ("max_drawdown", "{:.1%}"), ("final_equity", "${:,.0f}")]:
            lines.append(f"{key:16}" + "".join(f"{fmt.format(c[key]):>20}" for c in cols.values()))
        if self.halted_on:
            lines.append(f"Drawdown kill-switch triggered on {self.halted_on}; stayed in cash afterwards.")
        return "\n".join(lines)


def run_backtest(cfg: Config, strategy: Strategy, prices: pd.DataFrame,
                 benchmark: pd.Series | None = None) -> BacktestResult:
    broker = PaperBroker(cfg.starting_cash, None, cfg.commission_per_trade, cfg.slippage_bps)
    risk = RiskManager(cfg.risk)
    warmup = strategy.lookback_days
    if len(prices) <= warmup:
        raise ValueError(f"Need more than {warmup} rows of prices for a backtest, got {len(prices)}")

    equity, dates = [], []
    peak, last_key, trades, halted_on = 0.0, None, 0, None
    for i in range(warmup, len(prices)):
        today = prices.index[i]
        latest = prices.iloc[i].to_dict()
        acct = broker.account(latest)
        peak = max(peak, acct.equity)
        key = period_key(today.date(), cfg.rebalance)
        if halted_on is None and key != last_key:
            decision = risk.apply(strategy.target_weights(prices.iloc[: i + 1]), acct.equity, peak)
            orders = plan_orders(acct.positions, latest, acct.cash, decision.weights,
                                 cfg.risk.min_trade_value, cfg.risk.rebalance_threshold, cfg.fractional_shares)
            broker.submit(orders, latest)
            trades += len(orders)
            last_key = key
            if decision.halt:
                halted_on = str(today.date())
        equity.append(broker.account(latest).equity)
        dates.append(today)

    eq = pd.Series(equity, index=dates, name="strategy")
    bench = None
    if benchmark is not None:
        b = benchmark.loc[eq.index[0]:eq.index[-1]]
        bench = (b / b.iloc[0] * cfg.starting_cash).rename(benchmark.name)
    return BacktestResult(eq, bench, trades, halted_on)
