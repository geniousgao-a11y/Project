"""Market data providers. All return a DataFrame of daily adjusted closes:
index = dates (ascending), columns = symbols."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd


class DataProvider(ABC):
    @abstractmethod
    def history(self, symbols: list[str], start: date, end: date | None = None) -> pd.DataFrame:
        """Daily adjusted close prices for ``symbols`` between ``start`` and ``end`` (inclusive)."""


def _clean(df: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    missing = [s for s in symbols if s not in df.columns]
    if missing:
        raise ValueError(f"No price data for: {missing}")
    df = df[symbols].sort_index().ffill().dropna(how="any")
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


class YahooProvider(DataProvider):
    """Free daily data via yfinance. Good enough for daily/monthly strategies."""

    def history(self, symbols, start, end=None):
        import yfinance as yf

        # yfinance's ``end`` is exclusive.
        end_excl = (pd.Timestamp(end) + pd.Timedelta(days=1)).date() if end else None
        raw = yf.download(symbols, start=start, end=end_excl, auto_adjust=True, progress=False)
        if raw.empty:
            raise ValueError(f"Yahoo returned no data for {symbols}")
        close = raw["Close"]
        if isinstance(close, pd.Series):
            close = close.to_frame(symbols[0])
        return _clean(close, symbols)


class CSVProvider(DataProvider):
    """Reads ``<data_dir>/<SYMBOL>.csv`` files with ``Date`` and ``Close`` columns."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)

    def history(self, symbols, start, end=None):
        frames = {}
        for sym in symbols:
            df = pd.read_csv(self.data_dir / f"{sym}.csv", parse_dates=["Date"], index_col="Date")
            frames[sym] = df["Close"]
        df = pd.DataFrame(frames).loc[pd.Timestamp(start) : pd.Timestamp(end) if end else None]
        return _clean(df, symbols)


class StaticProvider(DataProvider):
    """Serves a pre-built DataFrame. Handy for tests and demos."""

    def __init__(self, prices: pd.DataFrame):
        self.prices = prices

    def history(self, symbols, start, end=None):
        df = self.prices.loc[pd.Timestamp(start) : pd.Timestamp(end) if end else None]
        return _clean(df, symbols)


def synthetic_prices(symbols: list[str], days: int = 1000, seed: int = 0, start: str = "2020-01-01") -> pd.DataFrame:
    """Geometric-Brownian-motion prices with a different drift per symbol."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=days)
    drifts = np.linspace(-0.05, 0.15, len(symbols)) / 252
    vols = np.full(len(symbols), 0.18 / np.sqrt(252))
    rets = rng.normal(drifts, vols, size=(days, len(symbols)))
    prices = 100 * np.exp(np.cumsum(rets, axis=0))
    return pd.DataFrame(prices, index=idx, columns=symbols)


def make_provider(source: str, data_dir: str = "data") -> DataProvider:
    if source == "yahoo":
        return YahooProvider()
    if source == "csv":
        return CSVProvider(data_dir)
    raise ValueError(f"Unknown data_source: {source!r}")
