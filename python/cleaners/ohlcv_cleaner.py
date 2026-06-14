"""
Data cleaning and normalization for QuantForge.
Handles: missing values, survivorship bias notes, splits/dividends,
calendar alignment, outlier detection.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import polars as pl

logger = logging.getLogger(__name__)


def clean_ohlcv(df: pl.DataFrame, symbol: str = "") -> pl.DataFrame:
    """
    Standardize OHLCV data:
    - Ensure column names match C++ types (ts, open, high, low, close, volume)
    - Forward-fill up to 3 consecutive nulls
    - Flag and strip extreme outliers (>10 sd moves)
    - Sort by timestamp ascending
    - Add day-of-week column for calendar analysis
    """
    required = {"open", "high", "low", "close", "volume"}
    cols_lower = {c.lower() for c in df.columns}

    # Rename common variations
    if "date" in cols_lower:
        df = df.rename(
            {c: "ts" for c in df.columns if c.lower() in ("date", "timestamp", "datetime")}
        )

    # Forward fill small gaps
    for col in ["open", "high", "low", "close"]:
        if col in df.columns:
            df = df.with_columns(
                pl.col(col).forward_fill(limit=3)
            )
    if "volume" in df.columns:
        df = df.with_columns(pl.col("volume").fill_null(0))

    # Outlier flagging (without modifying data). Flag on daily *returns*, not
    # raw price level — a trending stock drifts many σ from its mean price
    # while never making an anomalous single-day move, so a price-level test
    # both misses real jumps and false-flags healthy trends.
    if "close" in df.columns and df["close"].drop_nulls().len() > 2:
        rets = df["close"].pct_change()
        mean = rets.mean()
        std = rets.std()
        if std and std > 0:
            outlier_count = rets.filter((rets - mean).abs() > 10 * std).len()
            if outlier_count > 0:
                logger.warning("%s: %d daily return outliers (>10σ) — possible "
                               "splits/bad ticks", symbol, outlier_count)

    # Add helper columns
    if "ts" in df.columns:
        df = df.sort("ts")
        df = df.with_columns(pl.col("ts").dt.weekday().alias("day_of_week"))

    # Drop rows where close is null
    df = df.drop_nulls(subset=["close"])

    return df


def align_to_trading_calendar(
    df: pl.DataFrame,
    date_column: str = "ts",
    fill_missing: bool = True
) -> pl.DataFrame:
    """
    Ensure one row per trading day.
    Fill missing days with previous close (for simulation continuity).
    """
    if df.height < 2:
        return df

    # Build complete date range
    dates = pl.Series(df[date_column].to_list())
    min_date = dates.min()
    max_date = dates.max()

    # Generate all weekdays in range
    all_dates = pl.date_range(
        min_date, max_date, interval="1d", eager=True
    )
    # polars dt.weekday() is 1=Monday … 7=Sunday, so Mon–Fri is 1..5.
    # (The old `< 5` test silently dropped every Friday.)
    all_dates = all_dates.filter(all_dates.dt.weekday() <= 5)  # Mon-Fri only

    # date_range yields a Date; match the source column's dtype (often
    # Datetime) so the join keys are compatible.
    all_dates = all_dates.cast(df.schema[date_column])

    date_df = pl.DataFrame({date_column: all_dates})

    # Left join to fill gaps
    result = date_df.join(df, on=date_column, how="left")

    if fill_missing:
        result = result.with_columns(
            pl.col("open").forward_fill(),
            pl.col("high").forward_fill(),
            pl.col("low").forward_fill(),
            pl.col("close").forward_fill(),
            pl.col("volume").fill_null(0),
        )

    return result


def detect_splits(df: pl.DataFrame, threshold: float = 0.40) -> list[dict]:
    """
    Detect likely stock splits (day-over-day drop > threshold).
    Returns list of {date, ratio_suspected} entries.
    """
    splits = []
    if df.height < 2:
        return splits

    df = df.sort("ts")
    closes = df["close"].to_list()
    dates = df["ts"].to_list()

    for i in range(1, len(closes)):
        ratio = closes[i] / closes[i - 1] if closes[i - 1] > 0 else 1.0
        if ratio < threshold:
            suspected = round(1.0 / ratio)
            splits.append({
                "date": dates[i],
                "ratio_suspected": f"1:{suspected}",
                "price_drop_pct": (1.0 - ratio) * 100
            })
            logger.info("Suspected split on %s: ~1:%d split (%.1f%% drop)",
                        dates[i], suspected, (1.0 - ratio) * 100)

    return splits


def normalize_volume(volume: pl.Series) -> pl.Series:
    """Z-score normalize volume for cross-symbol comparison."""
    mean = volume.mean()
    std = volume.std()
    if std and std > 0:
        return (volume - mean) / std
    return volume - mean
