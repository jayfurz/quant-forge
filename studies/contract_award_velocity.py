#!/usr/bin/env python3
"""
Contract Award Velocity — Signal Study

Hypothesis:
    Public defense-contract award acceleration contains sector-relative
    predictive information for publicly traded defense/aerospace companies.

Study:
    Universe: 25 public defense primes + tier-1 suppliers
    Feature:  contract_award_velocity_z
             = (90-day award dollars / trailing-2yr avg 90-day dollars)
             normalized per company (z-score within ticker)
    PIT:     ts_available = award start_date (when publicly knowable)
    Target:  20d, 60d, 120d forward return vs sector ETF
    Baseline: price momentum (63-day return)

Usage:
    python studies/contract_award_velocity.py [--years 3] [--out reports/contract_award_velocity/]
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from research import (
    FeatureStore,
    PointInTimeJoiner,
    ForwardReturnLabeler,
    SignalStudyRunner,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ── Defense Universe ───────────────────────────────────────────────
# Publicly traded defense primes and tier-1 suppliers
DEFENSE_UNIVERSE = {
    "LMT":  "Lockheed Martin",
    "RTX":  "Raytheon Technologies",
    "NOC":  "Northrop Grumman",
    "GD":   "General Dynamics",
    "BA":   "Boeing",
    "LHX":  "L3Harris Technologies",
    "HII":  "Huntington Ingalls",
    "TXT":  "Textron",
    "LDOS": "Leidos",
    "CACI": "CACI International",
    "SAIC": "Science Applications International",
    "KBR":  "KBR Inc",
    "CW":   "Curtiss-Wright",
    "HEI":  "HEICO Corporation",
    "TDG":  "TransDigm Group",
    "AXON": "Axon Enterprise",
    "KTOS": "Kratos Defense",
    "MRCY": "Mercury Systems",
    "AVAV": "AeroVironment",
    "PLTR": "Palantir Technologies",
    "BAH":  "Booz Allen Hamilton",
    "PSN":  "Parsons Corporation",
    "BWXT": "BWX Technologies",
    "SPR":  "Spirit AeroSystems",
    "WWD":  "Woodward Inc",
}

SECTOR_ETF = "ITA"  # iShares US Aerospace & Defense ETF (benchmark)


def build_contract_feature(
    vendor_ticker_map: dict[str, str],
    lookback_years: int = 3,
) -> pl.DataFrame:
    """
    Fetch USAspending data and build contract_award_velocity_z.

    Returns DataFrame with columns:
        symbol, ts_available, feature_name, feature_value,
        source, source_event_id, asof_date
    """
    from downloaders.gov_contracts import fetch_defense_contracts_by_vendor

    vendor_names = list(vendor_ticker_map.values())
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=lookback_years * 365)).strftime("%Y-%m-%d")

    logger.info("Fetching USAspending data for %d vendors (%s → %s)",
                 len(vendor_names), start_date, end_date)

    contracts = fetch_defense_contracts_by_vendor(vendor_names, start_date, end_date)

    if contracts.is_empty():
        logger.warning("No contract data returned from USAspending")
        return pl.DataFrame()

    logger.info("Got %d contract awards", contracts.height)

    # Build vendor → ticker reverse map
    vendor_to_ticker = {v: k for k, v in vendor_ticker_map.items()}

    # Normalize column names - check what's actually available
    cols = contracts.columns
    logger.info("Contract columns: %s", cols)

    # The API returns various field names. Find the relevant ones.
    amount_col = None
    for candidate in ["Award Amount", "award_amount", "federal_action_obligation",
                       "total_obligated_amount", "awarding_agency_name"]:
        if candidate in cols:
            if candidate != "awarding_agency_name":
                amount_col = candidate
                break

    vendor_col = None
    for candidate in ["Recipient Name", "recipient_name", "awardee_or_recipient_legal_entity_name"]:
        if candidate in cols:
            vendor_col = candidate
            break

    date_col = None
    for candidate in ["Start Date", "start_date", "period_of_performance_start_date",
                       "action_date", "award_date"]:
        if candidate in cols:
            date_col = candidate
            break

    agency_col = "Awarding Agency" if "Awarding Agency" in cols else (
        "awarding_agency_name" if "awarding_agency_name" in cols else None)

    if not amount_col or not vendor_col or not date_col:
        logger.error("Cannot find required columns. Available: %s", cols)
        return pl.DataFrame()

    logger.info("Using columns: amount=%s, vendor=%s, date=%s",
                 amount_col, vendor_col, date_col)

    # Build feature rows
    rows = []
    for row in contracts.iter_rows(named=True):
        vendor_name = str(row.get(vendor_col, "")).strip()
        ticker = vendor_to_ticker.get(vendor_name)
        if not ticker:
            # Try partial match
            for vn, tk in vendor_to_ticker.items():
                if vn.lower() in vendor_name.lower():
                    ticker = tk
                    break
        if not ticker:
            continue

        try:
            amount = float(row.get(amount_col, 0) or 0)
        except (ValueError, TypeError):
            amount = 0.0

        if amount <= 0:
            continue

        award_date_str = str(row.get(date_col, ""))
        try:
            award_date = datetime.strptime(award_date_str[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            continue

        agency = str(row.get(agency_col, "")) if agency_col else ""

        rows.append({
            "symbol": ticker,
            "ts_available": award_date,
            "feature_name": "contract_award_value",
            "feature_value": amount,
            "source": "usaspending",
            "source_event_id": str(row.get("Award ID", row.get("award_id", ""))),
            "asof_date": award_date,
            "agency": agency,
        })

    if not rows:
        logger.warning("No mapped contract rows after vendor matching")
        return pl.DataFrame()

    raw = pl.DataFrame(rows)

    # ── Build contract_award_velocity_z ────────────────────────────
    # For each ticker, compute rolling 90-day award total
    # Then normalize: velocity = 90d_total / trailing_2yr_avg_90d
    raw = raw.sort(["symbol", "ts_available"])

    # Aggregate daily award totals per symbol
    daily_awards = raw.group_by(["symbol", "ts_available"]).agg(
        pl.col("feature_value").sum().alias("daily_total")
    ).sort(["symbol", "ts_available"])

    # Rolling 90-day sum per symbol
    daily_awards = daily_awards.with_columns(
        pl.col("daily_total")
        .rolling_sum(window_size=90, min_periods=1)
        .over("symbol")
        .alias("rolling_90d_sum"),
        pl.col("daily_total")
        .rolling_sum(window_size=730, min_periods=1)
        .over("symbol")
        .alias("rolling_2yr_sum"),
    )

    # Average 90-day award over 2 years = rolling_2yr_sum / (730/90) = rolling_2yr_sum / 8.11
    # Actually: avg 90-day total = total 2yr / (2*365/90) ≈ total_2yr / 8.11
    # Let's use rolling mean over 730 days as a simpler approach
    daily_averages = daily_awards.with_columns(
        pl.col("daily_total")
        .rolling_mean(window_size=730, min_periods=90)
        .over("symbol")
        .alias("trailing_2yr_avg")
    )

    # velocity = 90d / trailing 2yr average
    velocity = daily_averages.with_columns(
        (pl.col("rolling_90d_sum") / pl.col("trailing_2yr_avg"))
        .alias("velocity_raw")
    )

    # Replace inf/nan
    velocity = velocity.with_columns(
        pl.when(pl.col("velocity_raw").is_infinite())
        .then(pl.lit(None, dtype=pl.Float64))
        .when(pl.col("velocity_raw").is_nan())
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col("velocity_raw"))
        .alias("velocity_raw")
    )

    # Z-score normalize per ticker
    velocity = velocity.with_columns([
        pl.col("velocity_raw").mean().over("symbol").alias("_mean"),
        pl.col("velocity_raw").std().over("symbol").alias("_std"),
    ])

    velocity = velocity.with_columns(
        ((pl.col("velocity_raw") - pl.col("_mean")) / pl.col("_std"))
        .alias("contract_award_velocity_z")
    )

    # Drop rows where velocity_z is null (not enough history)
    velocity = velocity.drop_nulls(subset=["contract_award_velocity_z"])

    # Build final feature DataFrame
    features = velocity.select([
        pl.col("symbol"),
        pl.col("ts_available"),
        pl.lit("contract_award_velocity_z").alias("feature_name"),
        pl.col("contract_award_velocity_z").alias("feature_value"),
        pl.lit("usaspending").alias("source"),
        pl.lit("").alias("source_event_id"),
        pl.col("ts_available").alias("asof_date"),
    ])

    logger.info("Built contract_award_velocity_z: %d rows for %d symbols",
                 features.height, features["symbol"].n_unique())

    return features


def get_price_data(
    symbols: list[str],
    start: str,
    end: str,
) -> pl.DataFrame:
    """Download or load cached OHLCV data."""
    from downloaders.ohlcv import download_batch

    logger.info("Downloading OHLCV for %d symbols + benchmark %s",
                 len(symbols), SECTOR_ETF)

    all_symbols = symbols + [SECTOR_ETF]
    data = download_batch(all_symbols, start, end, delay_s=0.3)

    if not data:
        logger.error("No price data downloaded")
        return pl.DataFrame()

    # Combine into single DataFrame
    frames = []
    for sym, df in data.items():
        if df.is_empty():
            continue
        df = df.with_columns(pl.lit(sym).alias("symbol"))
        df = df.rename({"ts": "date"}).select([
            "symbol", "date", "open", "high", "low", "close", "volume"
        ])
        frames.append(df)

    if not frames:
        return pl.DataFrame()

    combined = pl.concat(frames).sort(["symbol", "date"])
    logger.info("Combined price data: %d rows", combined.height)

    # Add benchmark close to each row
    bm = combined.filter(pl.col("symbol") == SECTOR_ETF).select([
        "date", pl.col("close").alias("benchmark_close")
    ])
    combined = combined.join(bm, on="date", how="left")

    return combined


def run_study(
    output_dir: str = "reports/contract_award_velocity",
    lookback_years: int = 3,
    horizons: list[int] | None = None,
):
    """Run the full contract award velocity signal study."""
    if horizons is None:
        horizons = [20, 60, 120]

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ── 1. Build features ──────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 1: Building contract award velocity feature")
    logger.info("=" * 60)

    features = build_contract_feature(DEFENSE_UNIVERSE, lookback_years)

    if features.is_empty():
        logger.error("No features generated. Check USAspending API or vendor names.")
        return

    store = FeatureStore("data/features")
    store.add_features(features)

    summary = store.feature_summary()
    logger.info("Feature store summary:\n%s", summary)

    # ── 2. Get price data ──────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 2: Loading price data")
    logger.info("=" * 60)

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=lookback_years * 365)).strftime("%Y-%m-%d")

    tickers = list(DEFENSE_UNIVERSE.keys())
    bars = get_price_data(tickers, start_date, end_date)

    if bars.is_empty():
        logger.error("No price data available")
        return

    # Filter to only defense tickers (not benchmark) for main analysis
    defense_bars = bars.filter(pl.col("symbol") != SECTOR_ETF)

    # ── 3. PIT join ────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 3: Point-in-time join (features → bars)")
    logger.info("=" * 60)

    joiner = PointInTimeJoiner(store)
    joined = joiner.join(defense_bars, feature_names=["contract_award_velocity_z"])

    coverage = joiner.join_summary(joined, ["contract_award_velocity_z"])
    logger.info("Feature coverage:\n%s", coverage)

    # ── 4. Forward returns ─────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 4: Computing forward returns (horizons: %s)",
                 ", ".join(f"{h}d" for h in horizons))
    logger.info("=" * 60)

    labeler = ForwardReturnLabeler(horizons=horizons)
    labeled = labeler.compute(joined)

    # ── 5. Build baseline (price momentum) ─────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 5: Building baseline features")
    logger.info("=" * 60)

    # 63-day price momentum as baseline
    labeled = labeled.with_columns(
        ((pl.col("close") / pl.col("close").shift(63).over("symbol") - 1) * 100)
        .alias("price_momentum_63d")
    )

    # ── 6. Run studies ─────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 6: Running signal studies")
    logger.info("=" * 60)

    runner = SignalStudyRunner(labeled)

    for horizon in horizons:
        forward_col = f"forward_{horizon}d_return"
        logger.info("\n--- %s ---", forward_col)

        # Primary feature
        report = runner.run(
            feature_name="contract_award_velocity_z",
            forward_col=forward_col,
        )
        runner.save_report(report, out / f"velocity_{horizon}d")

        # Baseline comparison (price momentum)
        baseline = runner.run(
            feature_name="price_momentum_63d",
            forward_col=forward_col,
        )
        runner.save_report(baseline, out / f"momentum_baseline_{horizon}d")

        # Print comparison
        vs = report["quintile_spread"]
        bs = baseline["quintile_spread"]
        logger.info(
            "  velocity_z spread: mean=%.3f%%, sharpe=%.2f | "
            "momentum spread: mean=%.3f%%, sharpe=%.2f",
            vs.get("mean_spread", 0), vs.get("sharpe", 0),
            bs.get("mean_spread", 0), bs.get("sharpe", 0),
        )

    # ── 7. Summary ─────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Study complete. Reports saved to %s/", out)
    logger.info("=" * 60)

    for p in sorted(out.rglob("*.csv")):
        logger.info("  %s", p.relative_to(out))
    for p in sorted(out.rglob("*.md")):
        logger.info("  %s", p.relative_to(out))
    for p in sorted(out.rglob("*.json")):
        logger.info("  %s", p.relative_to(out))

    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Contract Award Velocity — Signal Study"
    )
    parser.add_argument("--years", type=int, default=3,
                        help="Years of lookback data (default: 3)")
    parser.add_argument("--out", default="reports/contract_award_velocity",
                        help="Output directory")
    parser.add_argument("--horizons", default="20,60,120",
                        help="Forward return horizons (comma-separated days)")
    args = parser.parse_args()

    horizons = [int(h.strip()) for h in args.horizons.split(",")]

    run_study(
        output_dir=args.out,
        lookback_years=args.years,
        horizons=horizons,
    )
