from datetime import date

import pandas as pd
import pytest

from invest_agent.agent import InvestmentAgent, period_key
from invest_agent.backtest import run_backtest
from invest_agent.brokers import make_broker
from invest_agent.brokers.paper import PaperBroker
from invest_agent.config import Config, RiskConfig, load_config
from invest_agent.data import StaticProvider, synthetic_prices
from invest_agent.rebalance import plan_orders
from invest_agent.risk import RiskManager
from invest_agent.strategies import make_strategy

SYMBOLS = ["AAA", "BBB", "CCC", "DDD", "EEE"]


@pytest.fixture
def prices():
    return synthetic_prices(SYMBOLS, days=800, seed=1)


def test_plan_orders_sells_before_buys_and_respects_cash():
    orders = plan_orders(positions={"AAA": 10}, prices={"AAA": 100, "BBB": 50}, cash=0,
                         target_weights={"BBB": 1.0}, min_trade_value=1, rebalance_threshold=0)
    assert [o.side for o in orders] == ["sell", "buy"]
    assert orders[0].qty == 10
    assert orders[1].est_value <= 1000


def test_plan_orders_skips_small_drift():
    orders = plan_orders({"AAA": 10}, {"AAA": 100}, cash=10, target_weights={"AAA": 1.0},
                         min_trade_value=25, rebalance_threshold=0.02)
    assert orders == []


def test_plan_orders_whole_shares():
    orders = plan_orders({}, {"AAA": 300}, cash=1000, target_weights={"AAA": 1.0}, fractional=False)
    assert orders[0].qty == 3.0


def test_risk_caps_and_keeps_cash():
    rm = RiskManager(RiskConfig(max_position_weight=0.4, min_cash_weight=0.1))
    d = rm.apply({"AAA": 0.8, "BBB": 0.6}, equity=100, peak_equity=100)
    assert all(w <= 0.4 + 1e-9 for w in d.weights.values())
    assert sum(d.weights.values()) <= 0.9 + 1e-9
    assert not d.halt


def test_risk_drawdown_halts():
    d = RiskManager(RiskConfig(max_drawdown=0.2)).apply({"AAA": 0.5}, equity=75, peak_equity=100)
    assert d.halt and d.weights == {}


def test_dual_momentum_picks_strongest(prices):
    strat = make_strategy("dual_momentum", top_n=2)
    w = strat.target_weights(prices)
    assert len(w) <= 2
    assert sum(w.values()) <= 1 + 1e-9
    scores = strat.scores(prices).sort_values(ascending=False)
    assert set(w) <= set(scores.index[:2])


def test_dual_momentum_safe_asset_when_all_falling():
    idx = pd.bdate_range("2020-01-01", periods=300)
    falling = pd.DataFrame({"AAA": range(400, 100, -1), "BBB": range(500, 200, -1), "BIL": [100] * 300},
                           index=idx, dtype=float)
    w = make_strategy("dual_momentum", top_n=2, safe_asset="BIL").target_weights(falling)
    assert w == {"BIL": pytest.approx(1.0)}


def test_sma_trend_excludes_downtrends():
    idx = pd.bdate_range("2020-01-01", periods=250)
    df = pd.DataFrame({"UP": range(100, 350), "DOWN": range(350, 100, -1)}, index=idx, dtype=float)
    assert set(make_strategy("sma_trend", window=200).target_weights(df)) == {"UP"}


def test_paper_broker_persists(tmp_path):
    path = tmp_path / "acct.json"
    b = PaperBroker(1000, path, slippage_bps=0)
    orders = plan_orders({}, {"AAA": 10}, 1000, {"AAA": 0.5}, rebalance_threshold=0)
    b.submit(orders, {"AAA": 10})
    b2 = PaperBroker(1000, path)
    assert b2.positions["AAA"] == pytest.approx(50)
    assert b2.cash == pytest.approx(500)


def test_backtest_runs(prices):
    cfg = Config(universe=SYMBOLS, rebalance="monthly")
    strat = make_strategy("dual_momentum", top_n=2)
    res = run_backtest(cfg, strat, prices, benchmark=prices["EEE"])
    assert res.trades > 0
    assert len(res.equity) == len(prices) - strat.lookback_days
    assert "cagr" in res.stats()
    assert "Strategy" in res.report()


def test_agent_run_once_and_period_skip(tmp_path, prices):
    cfg = Config(universe=SYMBOLS, state_dir=str(tmp_path), starting_cash=10_000)
    strat = make_strategy("dual_momentum", top_n=2)
    agent = InvestmentAgent(cfg, make_broker(cfg), StaticProvider(prices), strat)
    as_of = prices.index[-1].date()

    dry = agent.run_once(as_of=as_of, dry_run=True)
    assert dry.action == "dry_run" and dry.orders
    assert not (tmp_path / "journal.jsonl").exists()

    report = agent.run_once(as_of=as_of)
    assert report.action == "rebalanced"
    assert (tmp_path / "journal.jsonl").exists()

    again = InvestmentAgent(cfg, make_broker(cfg), StaticProvider(prices), strat).run_once(as_of=as_of)
    assert again.action == "skipped"


def test_live_requires_env_confirmation(monkeypatch):
    monkeypatch.delenv("INVEST_AGENT_LIVE", raising=False)
    cfg = Config(broker="alpaca", live_trading=True)
    with pytest.raises(RuntimeError, match="Refusing"):
        make_broker(cfg)


def test_period_key():
    assert period_key(date(2026, 9, 30), "monthly") == "2026-09"
    assert period_key(date(2026, 9, 30), "weekly") == "2026-W40"


def test_example_config_loads():
    cfg = load_config("config.example.yaml")
    assert cfg.broker == "paper" and not cfg.live_trading
    make_strategy(cfg.strategy, **cfg.strategy_params)
