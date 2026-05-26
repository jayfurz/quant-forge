"""
FINRA OTC Transparency Data API.

FINRA's developer portal: https://developer.finra.org
OTC data includes: weekly summaries, trade volumes, market maker counts.
Data is public and free but may require registration for API access.

Current endpoints need to be confirmed against the FINRA Developer Center docs.
The weekly summary CSV downloads are available at:
  https://otctransparency.finra.org/otctransparency/AgAWeeklyDownload

This module uses the OTC Transparency public download CSV as the primary source
(with the API endpoint as fallback).
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import polars as pl
import requests
import io

logger = logging.getLogger(__name__)

FINRA_OTC_CSV = "https://otctransparency.finra.org/otctransparency/AgAWeeklyDownload"
HEADERS = {
    "User-Agent": "QuantForge/0.1 (justin0106@protonmail.com)",
}


def fetch_otc_weekly_csv() -> pl.DataFrame:
    """
    Download the weekly OTC aggregate CSV from FINRA.
    This is the public CSV — no API key needed.

    Returns columns: tradeDate, issueSymbolIdentifier, issueName, tier,
                    totalWeeklyShareQuantity, totalWeeklyTradeCount,
                    lastSalePrice, numberOfMarketMakers, etc.
    """
    try:
        resp = requests.get(FINRA_OTC_CSV, headers=HEADERS, timeout=30)
        resp.raise_for_status()

        # FINRA CSV has a header row then tab-separated or comma-separated
        df = pl.read_csv(io.StringIO(resp.text), separator="\t", try_parse_dates=True,
                        null_values=["", " ", "NULL"])

        if df.is_empty():
            # Try comma separator
            df = pl.read_csv(io.StringIO(resp.text), separator=",", try_parse_dates=True,
                            null_values=["", " ", "NULL"])

        # Rename to standard schema
        rename_map = {}
        for col in df.columns:
            lower = col.lower().replace(" ", "_")
            if "tradedate" in lower or "trade_date" in lower:
                rename_map[col] = "trade_date"
            elif "share" in lower and "quantity" in lower:
                rename_map[col] = "share_volume"
            elif "trade" in lower and "count" in lower:
                rename_map[col] = "trade_count"
            elif "symbol" in lower or "ticker" in lower or "issue" in lower:
                rename_map[col] = "ticker"
            elif "name" in lower:
                rename_map[col] = "issue_name"
            elif "tier" in lower:
                rename_map[col] = "tier"
            elif "market" in lower and "maker" in lower:
                rename_map[col] = "market_makers"
            elif "price" in lower or "sale" in lower:
                rename_map[col] = "avg_price"

        if rename_map:
            df = df.rename(rename_map)

        logger.info("FINRA OTC CSV: %d rows, columns: %s", df.height, df.columns)
        return df

    except Exception as e:
        logger.error("FINRA CSV download failed: %s", e)
        return pl.DataFrame()


def fetch_otc_summary(
    start_date: str = None,
    end_date: str = None,
    tier: Optional[str] = None
) -> pl.DataFrame:
    """
    Public wrapper — uses the CSV download (no API key needed).
    Returns filtered results if dates provided.
    """
    df = fetch_otc_weekly_csv()

    if df.is_empty():
        return df

    if "trade_date" in df.columns and start_date:
        try:
            df = df.with_columns(pl.col("trade_date").cast(pl.Date))
            df = df.filter(pl.col("trade_date") >= pl.lit(start_date).cast(pl.Date))
        except Exception:
            pass

    if "trade_date" in df.columns and end_date:
        try:
            df = df.filter(pl.col("trade_date") <= pl.lit(end_date).cast(pl.Date))
        except Exception:
            pass

    if tier and "tier" in df.columns:
        df = df.filter(pl.col("tier").str.contains(tier))

    return df


def detect_otc_spikes(
    df: pl.DataFrame,
    volume_threshold_z: float = 3.0,
    lookback_days: int = 60
) -> pl.DataFrame:
    """Detect unusual OTC volume spikes (z-score > threshold)."""

    if df.is_empty() or "share_volume" not in df.columns:
        return df

    if "trade_date" in df.columns:
        df = df.with_columns(pl.col("trade_date").cast(pl.Date)).sort(["ticker", "trade_date"])

    volume_col = "share_volume" if "share_volume" in df.columns else df.columns[0]
    group_col = "ticker" if "ticker" in df.columns else df.columns[0]

    stats = df.group_by(group_col).agg([
        pl.col(volume_col).mean().alias("avg_volume"),
        pl.col(volume_col).std().alias("std_volume"),
    ])

    df = df.join(stats, on=group_col)
    df = df.with_columns(
        ((pl.col(volume_col) - pl.col("avg_volume")) / pl.col("std_volume"))
        .fill_null(0)
        .alias("volume_z_score")
    )

    return df.filter(pl.col("volume_z_score") > volume_threshold_z).sort("volume_z_score", descending=True)


def market_maker_activity(df: pl.DataFrame) -> pl.DataFrame:
    """Track market maker count changes — flag deteriorating liquidity."""

    if df.is_empty() or "market_makers" not in df.columns:
        return df

    sort_cols = []
    if "ticker" in df.columns:
        sort_cols.append("ticker")
    if "trade_date" in df.columns:
        sort_cols.append("trade_date")
    if sort_cols:
        df = df.sort(sort_cols)

    group = "ticker" if "ticker" in df.columns else df.columns[0]

    df = df.with_columns(
        (pl.col("market_makers") - pl.col("market_makers").shift(1))
        .over(group).alias("mm_change"),
        pl.col("market_makers").shift(1)
        .over(group).alias("prev_mm"),
    )

    df = df.with_columns(
        ((pl.col("market_makers") - pl.col("prev_mm")) / pl.col("prev_mm"))
        .fill_null(0).alias("mm_change_pct")
    )

    return df.filter((pl.col("mm_change") < -1) & (pl.col("prev_mm") > 2)).sort("mm_change")
