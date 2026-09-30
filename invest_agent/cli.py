"""Command-line interface: ``invest-agent <command>`` or ``python -m invest_agent <command>``."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from .agent import AgentState, InvestmentAgent, universe_symbols
from .backtest import run_backtest
from .brokers import make_broker
from .config import load_config
from .data import StaticProvider, make_provider, synthetic_prices
from .strategies import STRATEGIES, make_strategy


def _setup(args):
    cfg = load_config(args.config)
    strategy = make_strategy(cfg.strategy, **cfg.strategy_params)
    return cfg, strategy


def cmd_backtest(args) -> int:
    cfg, strategy = _setup(args)
    symbols = universe_symbols(cfg, strategy)
    bench_sym = cfg.benchmark.upper() if cfg.benchmark else None
    fetch = symbols + ([bench_sym] if bench_sym and bench_sym not in symbols else [])
    if args.demo:
        data = StaticProvider(synthetic_prices(fetch, days=2000, seed=42, start="2015-01-01"))
    else:
        data = make_provider(cfg.data_source, cfg.data_dir)
    end = date.fromisoformat(args.end) if args.end else date.today()
    all_prices = data.history(fetch, date.fromisoformat(args.start), end)
    benchmark = all_prices[bench_sym] if bench_sym else None
    result = run_backtest(cfg, strategy, all_prices[symbols], benchmark)
    print(f"Strategy: {cfg.strategy} {cfg.strategy_params}  rebalance: {cfg.rebalance}")
    print(result.report())
    if args.output:
        pd.DataFrame({"strategy": result.equity, "benchmark": result.benchmark}).to_csv(args.output)
        print(f"Equity curve written to {args.output}")
    return 0


def cmd_run(args) -> int:
    cfg, strategy = _setup(args)
    broker = make_broker(cfg)
    if not args.dry_run and not args.ignore_market_hours and not broker.market_open():
        print("Market is closed; not trading. Use --ignore-market-hours to queue orders anyway.")
        return 0
    agent = InvestmentAgent(cfg, broker, make_provider(cfg.data_source, cfg.data_dir), strategy)
    report = agent.run_once(dry_run=args.dry_run, force=args.force)
    print(report.summary())
    return 0


def cmd_status(args) -> int:
    cfg, strategy = _setup(args)
    broker = make_broker(cfg)
    state = AgentState(Path(cfg.state_dir) / "agent_state.json")
    held_prices = {}
    if cfg.broker == "paper":
        held = list(getattr(broker, "positions", {}))
        if held:
            prices = make_provider(cfg.data_source, cfg.data_dir).history(
                held, (pd.Timestamp.today() - pd.Timedelta(days=10)).date())
            held_prices = prices.iloc[-1].to_dict()
    acct = broker.account(held_prices)
    print(f"Broker: {cfg.broker} ({'LIVE' if broker.is_live else 'paper'})")
    print(f"Equity: ${acct.equity:,.2f}   Cash: ${acct.cash:,.2f}   Peak: ${state.peak_equity:,.2f}")
    print(f"Halted: {state.halted}   Last rebalance: {state.last_rebalance}")
    for sym, qty in sorted(acct.positions.items()):
        px = held_prices.get(sym)
        value = f"  ${qty * px:,.2f}" if px else ""
        print(f"  {sym:6} {qty:12.4f}{value}")
    return 0


def cmd_reset_halt(args) -> int:
    cfg = load_config(args.config)
    state = AgentState(Path(cfg.state_dir) / "agent_state.json")
    state.halted = False
    state.peak_equity = 0.0  # restart drawdown tracking from current equity
    state.save()
    print("Halt cleared. Drawdown tracking restarts from the next run's equity.")
    return 0


def cmd_strategies(args) -> int:
    for name, cls in sorted(STRATEGIES.items()):
        doc = (cls.__doc__ or "").strip().splitlines()[0]
        print(f"{name:16} {doc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="invest-agent", description="Rules-based investment agent")
    p.add_argument("-c", "--config", default="config.yaml", help="YAML config (default: config.yaml)")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("backtest", help="Replay the strategy over history")
    b.add_argument("--start", default="2012-01-01")
    b.add_argument("--end")
    b.add_argument("--demo", action="store_true", help="Use synthetic prices (offline)")
    b.add_argument("--output", help="Write the equity curve to this CSV")
    b.set_defaults(func=cmd_backtest)

    r = sub.add_parser("run", help="Run one decision cycle against the configured broker")
    r.add_argument("--dry-run", action="store_true", help="Show orders without placing them")
    r.add_argument("--force", action="store_true", help="Rebalance even if already done this period")
    r.add_argument("--ignore-market-hours", action="store_true")
    r.set_defaults(func=cmd_run)

    sub.add_parser("status", help="Show account, positions and agent state").set_defaults(func=cmd_status)
    sub.add_parser("reset-halt", help="Resume after a drawdown halt").set_defaults(func=cmd_reset_halt)
    sub.add_parser("strategies", help="List available strategies").set_defaults(func=cmd_strategies)

    args = p.parse_args(argv)
    if args.config == "config.yaml" and not os.path.exists("config.yaml"):
        args.config = None  # fall back to built-in defaults
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
