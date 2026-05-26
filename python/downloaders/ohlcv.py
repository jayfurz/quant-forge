"""
OHLCV data downloader.
Sources: Yahoo Finance (free), Alpha Vantage (free tier), Tiingo.
"""

import csv
import io
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
import polars as pl

logger = logging.getLogger(__name__)

# ── Yahoo Finance ─────────────────────────────────────────────────
YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

def download_yahoo(
    symbol: str,
    start: str,        # YYYY-MM-DD
    end: str,
    interval: str = "1d",  # 1d, 1wk, 1mo
    output_dir: Optional[Path] = None
) -> pl.DataFrame:
    """
    Download OHLCV from Yahoo Finance v8 API.
    Returns DataFrame with columns: ts, open, high, low, close, volume
    """
    period1 = int(datetime.strptime(start, "%Y-%m-%d").timestamp())
    period2 = int(datetime.strptime(end, "%Y-%m-%d").timestamp())

    params = {
        "symbol": symbol,
        "period1": period1,
        "period2": period2,
        "interval": interval,
        "includePrePost": "false",
        "events": "div|split"
    }

    resp = requests.get(
        f"{YAHOO_BASE}/{symbol}",
        params=params,
        headers={"User-Agent": "QuantForge/0.1"}
    )
    resp.raise_for_status()
    data = resp.json()

    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    quotes = result["indicators"]["quote"][0]

    df = pl.DataFrame({
        "ts":     [datetime.fromtimestamp(t) for t in timestamps],
        "open":   quotes["open"],
        "high":   quotes["high"],
        "low":    quotes["low"],
        "close":  quotes["close"],
        "volume": quotes["volume"]
    })

    # Drop rows with null OHLC (non-trading days)
    df = df.drop_nulls(subset=["open", "high", "low", "close"])

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{symbol}_{interval}.csv"
        df.write_csv(path)
        logger.info("Wrote %s rows to %s", df.height, path)

    return df


# ── Batch Download ────────────────────────────────────────────────
def download_batch(
    symbols: list[str],
    start: str,
    end: str,
    interval: str = "1d",
    output_dir: str = "data/market_data",
    delay_s: float = 0.5
) -> dict[str, pl.DataFrame]:
    """
    Download multiple symbols with rate limiting.
    Returns dict[symbol -> DataFrame].
    """
    out = Path(output_dir)
    results = {}

    for i, sym in enumerate(symbols):
        try:
            df = download_yahoo(sym, start, end, interval, out)
            results[sym] = df
            logger.info("[%d/%d] %s: %d rows", i + 1, len(symbols), sym, df.height)
        except Exception as e:
            logger.error("[%d/%d] %s FAILED: %s", i + 1, len(symbols), sym, e)

        if i < len(symbols) - 1:
            time.sleep(delay_s)

    return results


# ── S&P 500 Symbol List ──────────────────────────────────────────
def fetch_sp500_symbols() -> list[str]:
    """Scrape current S&P 500 constituents from Wikipedia."""
    tables = pl.read_html(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    )
    # First table on the page
    df = tables[0]
    return df["Symbol"].to_list()
