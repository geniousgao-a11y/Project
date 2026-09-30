from __future__ import annotations

from pathlib import Path

from ..config import Config
from .base import Account, Broker, Fill
from .paper import PaperBroker


def make_broker(cfg: Config) -> Broker:
    if cfg.broker == "paper":
        return PaperBroker(cfg.starting_cash, Path(cfg.state_dir) / "paper_account.json",
                           cfg.commission_per_trade, cfg.slippage_bps)
    if cfg.broker == "alpaca":
        from .alpaca import AlpacaBroker

        if cfg.live_trading and not cfg.live_confirmed:
            raise RuntimeError(
                "live_trading is true but INVEST_AGENT_LIVE is not set to I_UNDERSTAND_THE_RISKS. "
                "Refusing to trade real money."
            )
        return AlpacaBroker(live=cfg.live_confirmed)
    raise ValueError(f"Unknown broker: {cfg.broker!r}")


__all__ = ["Account", "Broker", "Fill", "PaperBroker", "make_broker"]
