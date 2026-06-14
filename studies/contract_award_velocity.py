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
    build_award_velocity,
    build_trailing_obligations,
    fama_macbeth,
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

# ── Wider federal-contractor universe ──────────────────────────────
# Defense/aerospace + government IT services + federally-exposed industrials.
# The point is cross-sectional breadth: a ~24-name universe caps every t-stat,
# so this roughly doubles it. Mapping is keyword-based (USAspending recipient
# search), so a few names match imperfectly — those self-filter via low coverage.
_WIDE_ADDITIONS = {
    # aerospace / defense components & systems
    "HWM":  "Howmet Aerospace",
    "TDY":  "Teledyne",
    "DCO":  "Ducommun",
    "TGI":  "Triumph Group",
    "OSK":  "Oshkosh",
    "DRS":  "Leonardo DRS",
    "HXL":  "Hexcel",
    "VSAT": "Viasat",
    "ESLT": "Elbit Systems",
    "RKLB": "Rocket Lab",
    "CR":   "Crane Company",
    "MOG-A": "Moog",
    # government IT / engineering services
    "ACN":  "Accenture Federal",
    "ICFI": "ICF International",
    "ACM":  "AECOM",
    "J":    "Jacobs Solutions",
    "AMTM": "Amentum",
    "VVX":  "V2X",
    "DXC":  "DXC Technology",
    "GD":   "General Dynamics",  # (already present; dict dedupes)
    # diversified industrials with material federal exposure
    "HON":  "Honeywell",
    "GE":   "GE Aerospace",
    "CAT":  "Caterpillar",
    "EMR":  "Emerson Electric",
}
WIDE_UNIVERSE = {**DEFENSE_UNIVERSE, **_WIDE_ADDITIONS}

UNIVERSES = {"defense": DEFENSE_UNIVERSE, "wide": WIDE_UNIVERSE}

SECTOR_ETF = "ITA"  # iShares US Aerospace & Defense ETF (benchmark)


def build_contract_feature(
    vendor_ticker_map: dict[str, str],
    lookback_years: int = 3,
    reporting_lag_days: int = 45,
) -> pl.DataFrame:
    """
    Fetch monthly USAspending obligation totals and build a point-in-time
    contract_award_velocity_z feature.

    Uses the ``spending_over_time`` endpoint (server-aggregated monthly
    obligations, complete and untruncated) rather than the award endpoint
    (cumulative current obligation stamped at a single PoP-start date — a
    lookahead trap) or raw transaction pagination (which truncates the oldest
    history for high-volume primes). See
    reports/contract_award_velocity/RESEARCH_NOTES.md. The velocity /
    trailing-z-score / reporting-lag logic lives in
    research.features.build_award_velocity so it is testable in isolation.

    Returns the FeatureStore schema:
        symbol, ts_available, feature_name, feature_value,
        source, source_event_id, asof_date
    """
    from downloaders.gov_contracts import fetch_monthly_obligations_by_vendor

    vendor_names = list(vendor_ticker_map.values())
    # Pull extra history so the trailing baseline window is warm by the time the
    # study's price sample starts.
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=(lookback_years + 3) * 365)).strftime("%Y-%m-%d")

    logger.info("Fetching USAspending monthly obligations for %d vendors (%s → %s)",
                 len(vendor_names), start_date, end_date)

    monthly = fetch_monthly_obligations_by_vendor(vendor_names, start_date, end_date)

    if monthly.is_empty():
        logger.warning("No monthly obligation data returned from USAspending")
        return pl.DataFrame()

    logger.info("Got %d vendor-months", monthly.height)

    # Map the search-keyword vendor name → ticker (keyword == universe name).
    vendor_to_ticker = {v: k for k, v in vendor_ticker_map.items()}
    monthly = monthly.with_columns(
        pl.col("vendor").replace_strict(vendor_to_ticker, default=None).alias("symbol")
    ).drop_nulls(subset=["symbol"])

    if monthly.is_empty():
        logger.warning("No vendor-months mapped to universe tickers")
        return pl.DataFrame()

    # build_award_velocity treats each row as a dated obligation total; the
    # monthly month-end date is the natural action_date here.
    obl = monthly.select(["symbol", pl.col("month").alias("action_date"), "amount"])

    velocity = build_award_velocity(
        obl, recent_days=90, baseline_days=730, reporting_lag_days=reporting_lag_days,
    )
    # Raw trailing-12-month dollar obligations — the "size" numerator that the
    # velocity ratio discards (combined with market cap → contract intensity).
    ttm = build_trailing_obligations(
        obl, window_days=365, reporting_lag_days=reporting_lag_days,
    )

    parts = [f for f in (velocity, ttm) if not f.is_empty()]
    if not parts:
        logger.warning("No contract features produced")
        return pl.DataFrame()

    features = pl.concat(parts, how="diagonal_relaxed")
    logger.info("Built contract features: %d rows (%s)", features.height,
                 ", ".join(features["feature_name"].unique().to_list()))
    return features


def build_size_features(vendor_ticker_map: dict[str, str]) -> pl.DataFrame:
    """
    Fetch point-in-time shares outstanding (SEC dei cover-page count) for the
    universe and emit it as a FeatureStore feature (`shares_outstanding`), so it
    PIT-joins to bars like any other signal and lets us form market cap without
    lookahead.
    """
    from downloaders.sec_edgar import fetch_shares_outstanding

    frames = []
    for ticker in vendor_ticker_map:
        df = fetch_shares_outstanding(ticker)
        if not df.is_empty():
            frames.append(df)
    if not frames:
        logger.warning("No shares-outstanding data fetched")
        return pl.DataFrame()

    shares = pl.concat(frames, how="diagonal_relaxed")
    return shares.select([
        pl.col("symbol"),
        pl.col("ts_available"),
        pl.lit("shares_outstanding").alias("feature_name"),
        pl.col("shares").alias("feature_value"),
        pl.lit("sec_edgar").alias("source"),
        pl.lit("").alias("source_event_id"),
        pl.col("ts_available").alias("asof_date"),
    ])


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


def _write_fama_macbeth_md(path, fm_out: dict, horizons: list[int], models: dict):
    """Render Fama–MacBeth coefficients/t-stats to a markdown table."""
    lines = [
        "# Fama–MacBeth — incremental predictive power",
        "",
        "Cross-sectional regression of forward return on standardized features,",
        "averaged across non-overlapping periods. `t` is the Fama–MacBeth t-stat",
        "(|t| ≳ 2 ⇒ the feature adds information beyond the others).",
        "",
    ]
    for name, feats in models.items():
        lines += [f"## {name}", "",
                  "| horizon | n | " + " | ".join(feats) + " |",
                  "|---|---|" + "|".join(["---"] * len(feats)) + "|"]
        for h in horizons:
            res = fm_out.get(f"{name}_{h}d")
            if not res:
                continue
            cells = []
            for f in feats:
                c = res["coefficients"].get(f, {})
                cells.append(f"b={c.get('mean', 0):+.3f}, t={c.get('t_stat', 0):+.2f}")
            lines.append(f"| {h}d | {res['n_periods']} | " + " | ".join(cells) + " |")
        lines.append("")
    path.write_text("\n".join(lines) + "\n")


def run_study(
    output_dir: str = "reports/contract_award_velocity",
    lookback_years: int = 3,
    horizons: list[int] | None = None,
    universe: dict[str, str] | None = None,
):
    """Run the full contract award velocity signal study."""
    if horizons is None:
        horizons = [20, 60, 120]
    if universe is None:
        universe = DEFENSE_UNIVERSE

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ── 1. Build features ──────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 1: Building contract award velocity feature (%d names)",
                len(universe))
    logger.info("=" * 60)

    features = build_contract_feature(universe, lookback_years)

    if features.is_empty():
        logger.error("No features generated. Check USAspending API or vendor names.")
        return

    # Use a universe-scoped feature store so runs with different universes don't
    # collide / leak features into one another.
    store = FeatureStore(f"data/features/{out.name}")
    store.add_features(features)

    # Size input: point-in-time shares outstanding (for market-cap-relative
    # contract intensity).
    size_feats = build_size_features(universe)
    if not size_feats.is_empty():
        store.add_features(size_feats)

    summary = store.feature_summary()
    logger.info("Feature store summary:\n%s", summary)

    # ── 2. Get price data ──────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 2: Loading price data")
    logger.info("=" * 60)

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=lookback_years * 365)).strftime("%Y-%m-%d")

    tickers = list(universe.keys())
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

    pit_features = ["contract_award_velocity_z", "contract_oblig_ttm",
                    "shares_outstanding"]
    pit_features = [f for f in pit_features if f in store.feature_names()]

    joiner = PointInTimeJoiner(store)
    joined = joiner.join(defense_bars, feature_names=pit_features)

    coverage = joiner.join_summary(joined, pit_features)
    logger.info("Feature coverage:\n%s", coverage)

    # ── 4. Forward returns ─────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 4: Computing forward returns (horizons: %s)",
                 ", ".join(f"{h}d" for h in horizons))
    logger.info("=" * 60)

    labeler = ForwardReturnLabeler(horizons=horizons)
    labeled = labeler.compute(joined)

    # ── 5. Build derived features (momentum + contract intensity) ──
    logger.info("=" * 60)
    logger.info("STEP 5: Building baseline + size features")
    logger.info("=" * 60)

    # 63-day price momentum as baseline
    labeled = labeled.with_columns(
        ((pl.col("close") / pl.col("close").shift(63).over("symbol") - 1) * 100)
        .alias("price_momentum_63d")
    )

    # Contract intensity = trailing-12m obligations / market cap. This is the
    # "size of the contract relative to the company" signal — distinct from the
    # velocity *ratio*, which is scale-free. Market cap uses PIT shares.
    have_intensity = ("contract_oblig_ttm" in labeled.columns
                      and "shares_outstanding" in labeled.columns)
    if have_intensity:
        labeled = labeled.with_columns(
            (pl.col("close") * pl.col("shares_outstanding")).alias("market_cap")
        ).with_columns(
            pl.when(pl.col("market_cap") > 0)
            .then(pl.col("contract_oblig_ttm") / pl.col("market_cap"))
            .otherwise(None)
            .alias("contract_intensity")
        )
        cov = labeled["contract_intensity"].drop_nulls().len()
        logger.info("contract_intensity populated rows: %d / %d", cov, labeled.height)
    else:
        logger.warning("Missing oblig_ttm or shares — skipping contract_intensity")

    # ── 6. Run studies ─────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 6: Running signal studies")
    logger.info("=" * 60)

    runner = SignalStudyRunner(labeled)

    # Univariate studies per feature that exists.
    univariate = ["contract_award_velocity_z", "price_momentum_63d"]
    if have_intensity:
        univariate.append("contract_intensity")

    report_name = {
        "contract_award_velocity_z": "velocity",
        "price_momentum_63d": "momentum_baseline",
        "contract_intensity": "intensity",
    }

    for horizon in horizons:
        forward_col = f"forward_{horizon}d_return"
        logger.info("\n--- %s ---", forward_col)
        for feat in univariate:
            try:
                rep = runner.run(feature_name=feat, forward_col=forward_col)
            except ValueError as e:
                logger.warning("  %s skipped: %s", feat, e)
                continue
            runner.save_report(rep, out / f"{report_name[feat]}_{horizon}d")
            ic = rep["ic_summary"]
            logger.info("  %-26s IC=%+.4f t=%+.2f spread=%+.3f%%",
                         feat, ic["pearson_ic_mean"], ic["ic_t_stat"],
                         rep["quintile_spread"]["mean_spread"])

    # ── 6b. Orthogonalization (Fama–MacBeth) ───────────────────────
    logger.info("=" * 60)
    logger.info("STEP 6b: Fama–MacBeth — does contract info survive controls?")
    logger.info("=" * 60)

    fm_models = {
        "velocity_vs_momentum": ["contract_award_velocity_z", "price_momentum_63d"],
    }
    if have_intensity:
        fm_models["intensity_vs_momentum"] = ["contract_intensity", "price_momentum_63d"]
        fm_models["all_three"] = [
            "contract_award_velocity_z", "contract_intensity", "price_momentum_63d"
        ]

    fm_out = {}
    for horizon in horizons:
        forward_col = f"forward_{horizon}d_return"
        for name, feats in fm_models.items():
            res = fama_macbeth(labeled, feats, forward_col=forward_col)
            fm_out[f"{name}_{horizon}d"] = res
            coefs = " | ".join(
                f"{f}: b={c['mean']:+.3f} t={c['t_stat']:+.2f}"
                for f, c in res["coefficients"].items()
            )
            logger.info("  [%s %dd, n=%d] %s", name, horizon, res["n_periods"], coefs)

    import json
    (out / "fama_macbeth.json").write_text(json.dumps(fm_out, indent=2, default=str))
    _write_fama_macbeth_md(out / "fama_macbeth.md", fm_out, horizons, fm_models)

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
    parser.add_argument("--universe", choices=list(UNIVERSES), default="defense",
                        help="Which universe to run (default: defense)")
    args = parser.parse_args()

    horizons = [int(h.strip()) for h in args.horizons.split(",")]

    run_study(
        output_dir=args.out,
        lookback_years=args.years,
        horizons=horizons,
        universe=UNIVERSES[args.universe],
    )
