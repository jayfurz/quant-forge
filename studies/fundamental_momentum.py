#!/usr/bin/env python3
"""
Fundamental Momentum — Signal Study

Hypothesis:
    Companies whose revenue growth is *accelerating* (rising year-over-year
    growth) outperform cross-sectionally — the fundamental-momentum / PEAD
    family of anomalies. Unlike the contract-data arc (a null), this is a
    documented effect, so it's a real test of whether the platform can detect a
    signal that is actually there.

Data:
    SEC XBRL revenue (point-in-time, stamped at the SEC `filed` date), a broad
    ~100-name large/mid-cap cross-section, prices from Yahoo, benchmark SPY.

Features:
    rev_yoy_growth  — revenue vs the same fiscal quarter a year earlier
    rev_yoy_accel   — change in that YoY growth (acceleration)
    price_momentum_63d — baseline control

Method: quintiles + IC (SignalStudyRunner) and Fama–MacBeth orthogonalization
against price momentum, over non-overlapping rebalances.

Usage:
    python studies/fundamental_momentum.py [--years 8]
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from research import (  # noqa: E402
    FeatureStore, ForwardReturnLabeler, PointInTimeJoiner, SignalStudyRunner,
    build_fundamental_momentum, fama_macbeth,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BENCHMARK = "SPY"

# Broad, sector-diversified large/mid-cap universe (~100 names) for
# cross-sectional power.
UNIVERSE = [
    # tech / semis / software
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "ORCL", "CRM",
    "ADBE", "AMD", "INTC", "CSCO", "QCOM", "TXN", "IBM", "NOW", "INTU", "AMAT", "MU",
    # comm / media
    "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS",
    # consumer discretionary
    "HD", "MCD", "NKE", "SBUX", "LOW", "TJX", "BKNG", "TGT", "TSLA", "F", "GM",
    # consumer staples
    "WMT", "PG", "KO", "PEP", "COST", "MDLZ", "CL",
    # health care
    "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "GILD", "CVS",
    # financials
    "JPM", "BAC", "WFC", "GS", "MS", "C", "AXP", "SCHW", "BLK", "SPGI",
    # industrials
    "CAT", "DE", "BA", "HON", "UNP", "UPS", "GE", "LMT", "RTX", "MMM",
    # energy / materials
    "XOM", "CVX", "COP", "SLB", "EOG", "LIN", "SHW", "FCX", "NEM",
    # utilities / REIT
    "NEE", "DUK", "SO", "AMT", "PLD",
]

FEATURES = ["rev_yoy_accel", "rev_yoy_growth", "price_momentum_63d"]


def build_features(universe, store: FeatureStore):
    from downloaders.sec_edgar import fetch_revenue_quarterly
    frames = []
    for tk in universe:
        df = fetch_revenue_quarterly(tk)
        if not df.is_empty():
            frames.append(df)
        time.sleep(0.12)  # respect SEC 10 req/s
    if not frames:
        return 0
    rev = pl.concat(frames, how="diagonal_relaxed")
    feats = build_fundamental_momentum(rev)
    if feats.is_empty():
        return 0
    store.add_features(feats)
    logger.info("Built fundamental features: %d rows for %d symbols (%s)",
                feats.height, feats["symbol"].n_unique(),
                ", ".join(feats["feature_name"].unique().to_list()))
    return feats.height


def load_prices(symbols, start, end):
    from downloaders.ohlcv import download_batch
    data = download_batch(symbols + [BENCHMARK], start, end, delay_s=0.25)
    frames = []
    for sym, df in data.items():
        if df.is_empty():
            continue
        frames.append(df.with_columns(pl.lit(sym).alias("symbol"))
                      .rename({"ts": "date"})
                      .select(["symbol", "date", "open", "high", "low", "close", "volume"]))
    if not frames:
        return pl.DataFrame()
    bars = pl.concat(frames).sort(["symbol", "date"])
    bm = bars.filter(pl.col("symbol") == BENCHMARK).select(
        ["date", pl.col("close").alias("benchmark_close")])
    return bars.join(bm, on="date", how="left").filter(pl.col("symbol") != BENCHMARK)


def run_study(output_dir="reports/fundamental_momentum", lookback_years=8,
              horizons=(20, 60, 120)):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    horizons = list(horizons)

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=lookback_years * 365)).strftime("%Y-%m-%d")

    logger.info("STEP 1: SEC revenue features (%d names)", len(UNIVERSE))
    store = FeatureStore(f"data/features/{out.name}")
    if build_features(UNIVERSE, store) == 0:
        logger.error("No fundamental features built")
        return

    logger.info("STEP 2: Prices")
    bars = load_prices(UNIVERSE, start, end)
    if bars.is_empty():
        logger.error("No price data")
        return

    logger.info("STEP 3: PIT join + forward returns + momentum")
    pit = [f for f in ("rev_yoy_growth", "rev_yoy_accel") if f in store.feature_names()]
    joined = PointInTimeJoiner(store).join(bars, feature_names=pit)
    logger.info("Coverage:\n%s", PointInTimeJoiner(store).join_summary(joined, pit))
    labeled = ForwardReturnLabeler(horizons=horizons).compute(joined)
    labeled = labeled.with_columns(
        ((pl.col("close") / pl.col("close").shift(63).over("symbol") - 1) * 100)
        .alias("price_momentum_63d"))

    logger.info("STEP 4: Univariate studies")
    runner = SignalStudyRunner(labeled)
    name = {"rev_yoy_accel": "accel", "rev_yoy_growth": "growth",
            "price_momentum_63d": "momentum"}
    for h in horizons:
        fcol = f"forward_{h}d_return"
        logger.info("--- %s ---", fcol)
        for feat in FEATURES:
            try:
                rep = runner.run(feature_name=feat, forward_col=fcol)
            except ValueError as e:
                logger.warning("  %s skipped: %s", feat, e)
                continue
            runner.save_report(rep, out / f"{name[feat]}_{h}d")
            ic = rep["ic_summary"]
            logger.info("  %-18s IC=%+.4f t=%+.2f spread=%+.3f%%", feat,
                        ic["pearson_ic_mean"], ic["ic_t_stat"],
                        rep["quintile_spread"]["mean_spread"])

    logger.info("STEP 5: Fama–MacBeth (accel + growth + momentum)")
    fm = {}
    for h in horizons:
        res = fama_macbeth(labeled, FEATURES, forward_col=f"forward_{h}d_return")
        fm[f"{h}d"] = res
        logger.info("  [%dd n=%d] %s", h, res["n_periods"], " | ".join(
            f"{f}: t={res['coefficients'][f]['t_stat']:+.2f}" for f in FEATURES))
    (out / "fama_macbeth.json").write_text(json.dumps(fm, indent=2, default=str))
    _fm_md(out / "fama_macbeth.md", fm, horizons)
    logger.info("Reports → %s/", out)
    return fm


def _fm_md(path, fm, horizons):
    lines = ["# Fundamental momentum — Fama–MacBeth", "",
             "t-stat of each standardized feature, `forward ~ "
             "accel + growth + momentum`, non-overlapping periods.", "",
             "| horizon | n | rev_yoy_accel | rev_yoy_growth | momentum |",
             "|---|---|---|---|---|"]
    for h in horizons:
        r = fm.get(f"{h}d")
        if not r:
            continue
        c = r["coefficients"]
        lines.append(f"| {h}d | {r['n_periods']} | "
                     f"t={c['rev_yoy_accel']['t_stat']:+.2f} | "
                     f"t={c['rev_yoy_growth']['t_stat']:+.2f} | "
                     f"t={c['price_momentum_63d']['t_stat']:+.2f} |")
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Fundamental Momentum — Signal Study")
    p.add_argument("--years", type=int, default=8)
    p.add_argument("--out", default="reports/fundamental_momentum")
    p.add_argument("--horizons", default="20,60,120")
    a = p.parse_args()
    run_study(a.out, a.years, [int(x) for x in a.horizons.split(",")])
