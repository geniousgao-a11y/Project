"""Configuration loading.

Everything the agent does is driven by a YAML file (see ``config.example.yaml``).
Secrets (broker API keys) never live in the config file; they come from
environment variables or a local ``.env`` file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

# Real-money trading needs BOTH ``live_trading: true`` in the config AND this
# exact value in the environment. It's a deliberate speed bump.
LIVE_ENV_VAR = "INVEST_AGENT_LIVE"
LIVE_ENV_VALUE = "I_UNDERSTAND_THE_RISKS"
REBALANCE_CHOICES = ("daily", "weekly", "monthly")


@dataclass
class RiskConfig:
    # No single holding may exceed this fraction of equity.
    max_position_weight: float = 0.35
    # Always keep at least this fraction of equity in cash.
    min_cash_weight: float = 0.02
    # If equity falls this far below its peak, liquidate and halt until a
    # human runs ``invest-agent reset-halt``. Set to 1.0 to disable.
    max_drawdown: float = 0.30
    # Skip orders smaller than this (in dollars) to avoid churn.
    min_trade_value: float = 25.0
    # Skip rebalancing a position whose weight drifted less than this.
    rebalance_threshold: float = 0.02


@dataclass
class Config:
    universe: list[str] = field(default_factory=lambda: ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"])
    strategy: str = "dual_momentum"
    strategy_params: dict[str, Any] = field(default_factory=dict)
    rebalance: str = "monthly"  # "daily", "weekly" or "monthly"
    broker: str = "paper"  # "paper" or "alpaca"
    data_source: str = "yahoo"  # "yahoo" or "csv"
    data_dir: str = "data"  # used by the csv data source
    benchmark: str = "SPY"
    starting_cash: float = 10_000.0  # paper broker / backtests only
    commission_per_trade: float = 0.0
    slippage_bps: float = 5.0
    fractional_shares: bool = True
    state_dir: str = "state"
    live_trading: bool = False
    risk: RiskConfig = field(default_factory=RiskConfig)

    @property
    def live_confirmed(self) -> bool:
        return self.live_trading and os.environ.get(LIVE_ENV_VAR) == LIVE_ENV_VALUE


def _build(cls, data: dict[str, Any]):
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"Unknown {cls.__name__} keys: {sorted(unknown)}")
    return cls(**data)


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines); never overrides real env vars."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def load_config(path: str | Path | None) -> Config:
    load_dotenv()
    if path is None or not Path(path).exists():
        if path is not None:
            raise FileNotFoundError(f"Config file not found: {path}")
        return Config()
    raw = yaml.safe_load(Path(path).read_text()) or {}
    risk = _build(RiskConfig, raw.pop("risk", {}) or {})
    cfg = _build(Config, raw)
    cfg.risk = risk
    cfg.universe = [s.upper() for s in cfg.universe]
    if cfg.rebalance not in REBALANCE_CHOICES:
        raise ValueError(f"rebalance must be one of {REBALANCE_CHOICES}")
    if not cfg.universe:
        raise ValueError("universe must contain at least one symbol")
    return cfg
