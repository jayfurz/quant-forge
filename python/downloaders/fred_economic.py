"""
FRED (Federal Reserve Economic Data) — macroeconomic indicators.

Free API key required: https://research.stlouisfed.org/useraccount/apikey

Key series for defense/infrastructure signals:
- Inflation: CPI, PCE, PPI
- Rates: Fed Funds, 10Y Treasury, TIPS breakeven
- Labor: unemployment, JOLTS, wages
- Industrial: capacity utilization, IP, durable goods
- Defense: federal defense spending, procurement
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import polars as pl
import requests

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"


# ── Key FRED Series ──────────────────────────────────────────────
FRED_SERIES = {
    # Inflation
    "CPI_ALL":       "CPIAUCSL",     # Consumer Price Index
    "CPI_CORE":      "CPILFESL",     # CPI less food & energy
    "PCE_CORE":      "PCEPILFE",     # PCE Core (Fed's preferred)
    "PPI_FINAL":     "PPIACO",       # Producer Price Index

    # Rates
    "FED_FUNDS":     "DFEDTARU",     # Fed Funds Target Upper
    "T10Y":          "DGS10",        # 10-Year Treasury
    "T2Y":           "DGS2",         # 2-Year Treasury
    "TIPS_10Y":      "DFII10",       # 10-Year TIPS (real yield)

    # Labor
    "UNEMPLOYMENT":  "UNRATE",       # Unemployment Rate
    "JOLTS_OPENINGS": "JTSJOL",      # Job Openings
    "AVG_WAGE":      "CES0500000003", # Avg Hourly Earnings

    # Industrial
    "CAP_UTIL":      "TCU",          # Capacity Utilization
    "IND_PROD":      "INDPRO",       # Industrial Production
    "DURABLE_GOODS": "DGORDER",      # Durable Goods Orders

    # Defense / Government
    "DEFENSE_SPEND": "FDEFX",        # Federal Defense Spending
    "GOV_CONSUMPTION": "FGEXPND",   # Government Consumption
    "FED_DEBT":      "GFDEBTN",      # Federal Debt

    # Money / Credit
    "M2":            "M2SL",         # M2 Money Supply
    "COMM_LOANS":    "BUSLOANS",     # Commercial & Industrial Loans

    # Market
    "VIX":           "VIXCLS",       # VIX (via FRED)
    "SP500":         "SP500",        # S&P 500
}


def fetch_series(
    series_id: str,
    api_key: str,
    start_date: str = "2020-01-01",
    end_date: str = "2025-12-31",
    frequency: str = "m",  # d=daily, m=monthly, q=quarterly, a=annual
) -> pl.DataFrame:
    """
    Fetch a single FRED series.
    Returns DataFrame with date and value columns.
    """
    url = f"{FRED_BASE}/series/observations"

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
        "observation_end": end_date,
        "frequency": frequency,
        "sort_order": "asc",
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        observations = data.get("observations", [])
        rows = []
        for obs in observations:
            val = obs.get("value", ".")
            if val != ".":  # FRED uses "." for missing
                try:
                    rows.append({
                        "date": obs["date"],
                        "value": float(val),
                    })
                except ValueError:
                    continue

        if not rows:
            return pl.DataFrame()

        df = pl.DataFrame(rows)
        df = df.with_columns(
            pl.col("date").cast(pl.Date),
            pl.lit(series_id).alias("series_id"),
            pl.lit(data.get("title", series_id)).alias("name"),
            pl.lit(data.get("units", "")).alias("units"),
        )
        return df

    except Exception as e:
        logger.error("FRED fetch %s failed: %s", series_id, e)
        return pl.DataFrame()


def fetch_economic_dashboard(
    api_key: str,
    series_map: dict = None,
    start_date: str = "2020-01-01",
    end_date: str = "2025-12-31",
) -> dict[str, pl.DataFrame]:
    """
    Fetch a full economic dashboard — all key series.

    Returns dict[series_name -> DataFrame].
    """
    series = series_map or FRED_SERIES
    results = {}

    for name, series_id in series.items():
        df = fetch_series(series_id, api_key, start_date, end_date)
        if not df.is_empty():
            results[name] = df
            latest = df["value"].tail(1)[0] if df.height > 0 else None
            logger.info("  %-20s: %s = %.4f", name, series_id, latest)

    return results


def yield_curve_spread(api_key: str) -> Optional[float]:
    """
    Compute 10Y-2Y Treasury spread.
    Negative spread has historically preceded recessions.
    """
    t10 = fetch_series(FRED_SERIES["T10Y"], api_key, "2024-01-01", "2025-12-31", "d")
    t2 = fetch_series(FRED_SERIES["T2Y"], api_key, "2024-01-01", "2025-12-31", "d")

    if t10.is_empty() or t2.is_empty():
        return None

    latest_10y = t10["value"].tail(1)[0]
    latest_2y = t2["value"].tail(1)[0]
    spread = latest_10y - latest_2y

    return spread


def defense_spending_trend(api_key: str) -> pl.DataFrame:
    """
    Federal defense spending — year-over-year change.
    Useful for defense sector revenue forecasting.
    """
    df = fetch_series(FRED_SERIES["DEFENSE_SPEND"], api_key, "2015-01-01", "2025-12-31", "q")

    if df.is_empty():
        return df

    df = df.sort("date")
    df = df.with_columns(
        pl.col("value").pct_change(4).over("series_id").alias("yoy_change_pct"),
        pl.col("value").diff(1).over("series_id").alias("qoq_change"),
    )

    return df


def macro_regime_signal(api_key: str) -> dict:
    """
    Build a macro regime classification from FRED data.

    Regimes:
    - RISK_ON: low rates, low inflation, growth accelerating
    - RISK_OFF: high inflation, tightening, slowing growth
    - STAGFLATION: high inflation, low growth
    - GOLDILOCKS: moderate everything
    
    Returns dict with regime + component scores.
    """
    dash = fetch_economic_dashboard(api_key)

    def latest(name: str) -> float:
        df = dash.get(name)
        return float(df["value"].tail(1)[0]) if df and df.height > 0 else 0.0

    inflation = latest("CPI_ALL")
    unemployment = latest("UNEMPLOYMENT")
    sp500_latest = latest("SP500")

    # Simple heuristic (can be refined)
    score = 0.0

    # Inflation: 2% optimal, >4% bad, <4% ok
    if inflation > 4.0:
        score -= 2.0
    elif inflation > 3.0:
        score -= 1.0
    elif 1.5 < inflation < 2.5:
        score += 1.0

    # Unemployment: 4-5% healthy, >6% worrying
    if unemployment > 6.0:
        score -= 1.5
    elif 4.0 <= unemployment <= 5.0:
        score += 0.5
    elif unemployment < 3.5:
        score += 1.0  # tight labor = demand strong

    # Normalize to [-3, +3]
    score = max(-3.0, min(3.0, score))

    regime = "NEUTRAL"
    if score > 1.0:
        regime = "RISK_ON"
    elif score > 0.25:
        regime = "GOLDILOCKS"
    elif score < -1.0:
        regime = "RISK_OFF"
    elif score < -0.25:
        regime = "STAGFLATION_LEANING"

    return {
        "macro_score": score,
        "regime": regime,
        "components": {
            "inflation_cpi": inflation,
            "unemployment": unemployment,
            "sp500_latest": sp500_latest,
        }
    }
