"""
FINRA OTC Transparency Data API.
Niche market microstructure data — trade-level OTC equity data.

Use case: spot unusual OTC activity before it appears in listed prices,
track liquidity shifts, detect wash sale patterns.
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import polars as pl
import requests

logger = logging.getLogger(__name__)

FINRA_BASE = "https://api.finra.org"
HEADERS = {
    "User-Agent": "QuantForge/0.1 (justin0106@protonmail.com)",
    "Accept": "application/json",
}

# ── OTC Equity Trading Summary ────────────────────────────────────
def fetch_otc_summary(
    start_date: str,
    end_date: str,
    tier: Optional[str] = None  # "OTCQX", "OTCQB", "Pink", "Grey"
) -> pl.DataFrame:
    """
    Fetch OTC equity trading summaries from FINRA.
    Shows daily trading volume/activity per OTC ticker.
    """
    url = f"{FINRA_BASE}/api/OTC/EquitySummary"

    payload = {
        "startDate": start_date,
        "endDate": end_date,
        "compareFilters": [
            {"compareType": "EQUAL", "fieldName": "reportingFacilityId",
             "fieldValue": "ALL"},
        ],
        "limit": 5000
    }

    if tier:
        payload["compareFilters"].append({
            "compareType": "EQUAL",
            "fieldName": "tier",
            "fieldValue": tier
        })

    try:
        resp = requests.post(url, json=payload, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for row in data:
            results.append({
                "trade_date": row.get("tradeDate"),
                "ticker": row.get("issueSymbolIdentifier"),
                "issue_name": row.get("issueName"),
                "tier": row.get("tier"),
                "share_volume": int(row.get("totalWeeklyShareQuantity", 0)),
                "trade_count": int(row.get("totalWeeklyTradeCount", 0)),
                "avg_price": float(row.get("lastSalePrice", 0) or 0),
                "dollar_volume": float(row.get("lastDollarVolume", 0) or 0),
                "market_makers": int(row.get("numberOfMarketMakers", 0)),
            })

        return pl.DataFrame(results)

    except Exception as e:
        logger.error("FINRA OTC summary failed: %s", e)
        return pl.DataFrame()


# ── OTC Trade Activity Spikes ─────────────────────────────────────
def detect_otc_spikes(
    df: pl.DataFrame,
    volume_threshold_z: float = 3.0,
    lookback_days: int = 60
) -> pl.DataFrame:
    """
    Detect unusual OTC volume spikes.
    Flags tickers where volume exceeds z-score threshold vs historical.
    """

    if df.is_empty():
        return df

    df = df.with_columns(pl.col("trade_date").cast(pl.Date)).sort(["ticker", "trade_date"])

    # Per-ticker volume stats
    stats = df.group_by("ticker").agg([
        pl.col("share_volume").mean().alias("avg_volume"),
        pl.col("share_volume").std().alias("std_volume"),
        pl.col("share_volume").tail(lookback_days).mean().alias("recent_avg"),
    ])

    # Join and compute z-scores
    df = df.join(stats, on="ticker")

    df = df.with_columns(
        ((pl.col("share_volume") - pl.col("avg_volume")) / pl.col("std_volume"))
        .fill_null(0)
        .alias("volume_z_score"),
        ((pl.col("recent_avg") - pl.col("avg_volume")) / pl.col("std_volume"))
        .fill_null(0)
        .alias("recent_volume_z"),
    )

    # Flag spikes
    spikes = df.filter(pl.col("volume_z_score") > volume_threshold_z)

    return spikes.sort("volume_z_score", descending=True)


# ── Market Maker Concentration ────────────────────────────────────
def market_maker_activity(
    df: pl.DataFrame
) -> pl.DataFrame:
    """
    Track market maker count changes — fewer MMs can signal
    liquidity deterioration or pending delisting/halt.
    """

    if df.is_empty():
        return df

    df = df.sort(["ticker", "trade_date"])

    # MoM change in market makers
    df = df.with_columns(
        (pl.col("market_makers") - pl.col("market_makers").shift(1))
        .over("ticker")
        .alias("mm_change"),
        pl.col("market_makers")
        .shift(1)
        .over("ticker")
        .alias("prev_mm"),
    )

    # Flag deteriorating liquidity
    df = df.with_columns(
        ((pl.col("market_makers") - pl.col("prev_mm")) / pl.col("prev_mm"))
        .fill_null(0)
        .alias("mm_change_pct")
    )

    liquidity_alerts = df.filter(
        (pl.col("mm_change") < -1) & (pl.col("prev_mm") > 2)
    )

    return liquidity_alerts.sort("mm_change")
