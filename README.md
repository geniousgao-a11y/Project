# Investment Agent

A rules-based investment agent. On each run it:

1. **Fetches** daily prices for a set of ETFs/stocks (Yahoo Finance by default)
2. **Decides** target portfolio weights with a pluggable **strategy**
3. **Applies risk rules**: position caps, a cash buffer, and a drawdown kill switch
4. **Rebalances** by turning target weights into buy/sell orders
5. **Executes** them through a pluggable **broker**: a local paper simulator (default) or [Alpaca](https://alpaca.markets)
6. **Journals** every decision to `state/journal.jsonl`

A **backtester** replays any strategy over history with the same risk and rebalancing code, so what you test is what runs.

> ⚠️ **Not financial advice. No profit is guaranteed.** Past or backtested performance doesn't predict future results, and you can lose money. The agent trades on paper unless you deliberately turn on live trading (see below). Your money stays in **your own** brokerage account, under your control.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp config.example.yaml config.yaml

invest-agent strategies                     # list strategies
invest-agent backtest --start 2010-01-01    # real historical data (Yahoo)
invest-agent backtest --demo                # synthetic data, works offline
invest-agent run --dry-run                  # show what it would trade today
invest-agent run                            # trade (local paper account by default)
invest-agent status                         # account, positions, agent state
```

## Strategies

| Name | Idea |
|---|---|
| `dual_momentum` (default) | Rank assets by blended 3/6/12-month return and hold the top N. Any pick with negative momentum moves to a safe asset (T-bills) or cash. |
| `sma_trend` | Hold each asset only while it's above its 200-day moving average. |

Both support `weighting: equal | inverse_vol`. Configure them in `config.yaml` under `strategy_params`.

**Adding a strategy:** create `invest_agent/strategies/my_strategy.py`, subclass `Strategy`, implement `lookback_days` and `target_weights(prices) -> {symbol: weight}`, decorate the class with `@register`, and import the module in `strategies/__init__.py`. It then works with `run` and `backtest` automatically.

## Risk controls (in `config.yaml` → `risk`)

- `max_position_weight`: cap on any single holding (default 35%)
- `min_cash_weight`: cash that's always kept (default 2%)
- `max_drawdown`: if equity falls this far below its peak, the agent **liquidates and halts** until you run `invest-agent reset-halt`
- `min_trade_value` / `rebalance_threshold`: skip tiny trades to avoid churn
- Rebalancing happens at most once per `rebalance` period (monthly by default), even if you run the agent every day

## Going from paper to real money

1. **Paper trade locally** (`broker: paper`) and review the backtests.
2. **Alpaca paper account:** sign up at alpaca.markets, copy the *paper* API keys into `.env` (see `.env.example`), and set `broker: alpaca`. Orders now go to Alpaca's simulated market.
3. **Live** (only when you're ready): fund your Alpaca account, use your *live* keys, set `live_trading: true` in `config.yaml`, **and** set `INVEST_AGENT_LIVE=I_UNDERSTAND_THE_RISKS` in the environment. Without both, the agent refuses to trade real money.

Start small. Alpaca supports fractional shares, so a few hundred dollars is enough to test the whole pipeline.

## Scheduling

Run once per trading day, shortly after the open. The agent only rebalances when a new period starts. Example cron entry (10:00 US/Eastern, Monday to Friday):

```cron
CRON_TZ=America/New_York
0 10 * * 1-5  cd /path/to/Project && .venv/bin/invest-agent run >> state/cron.log 2>&1
```

## Project layout

```
invest_agent/
  config.py         YAML config + safety settings
  data.py           price providers (Yahoo, CSV, static/synthetic)
  strategies/       strategy base class, registry, built-in strategies
  risk.py           risk manager (caps, cash buffer, drawdown halt)
  rebalance.py      target weights -> orders
  brokers/          paper simulator, Alpaca REST client
  agent.py          the trading loop + persistent state + journal
  backtest.py       historical simulation + performance stats
  cli.py            `invest-agent` command
tests/              offline unit tests (pytest)
```

## Roadmap / ideas for later

- [ ] More strategies: risk parity, value/quality factor screens, volatility targeting
- [ ] Walk-forward parameter optimisation, plus transaction-cost-aware backtests
- [ ] More brokers (Interactive Brokers, crypto exchanges via ccxt)
- [ ] Notifications (email/Slack) after each run, and a web dashboard for the journal
- [ ] LLM-assisted research layer (news/earnings summaries) feeding into a strategy, with its output always passed through the risk manager
- [ ] Tax-lot awareness / tax-loss harvesting

## Development

```bash
pytest -q
```
