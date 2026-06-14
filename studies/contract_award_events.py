#!/usr/bin/env python3
"""
Contract Award — Event Study

Hypothesis (event frame):
    A large, publicly-announced defense contract award produces an abnormal
    return (vs the sector ETF) in a tight window around the announcement —
    either an announcement-day reaction or a post-announcement drift.

This is the discrete-event complement to the cross-sectional factor study in
contract_award_velocity.py (which found no robust ranking signal). Large awards
are announced publicly by DoD on/near the obligation's action_date; we measure
cumulative abnormal return (CAR = stock − ITA) over [−5,−1], [0], [1,5],
[1,20], [1,60] trading days, with t-stats across events, and split by award size.

Usage:
    python studies/contract_award_events.py [--years 8] [--min-award 50e6]
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from research import EventStudy  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from contract_award_velocity import (  # noqa: E402
    DEFENSE_UNIVERSE, SECTOR_ETF, UNIVERSES, get_price_data,
)


def build_events(
    vendor_ticker_map: dict[str, str],
    start: str,
    end: str,
    min_award: float,
    cluster_days: int = 7,
) -> pl.DataFrame:
    """Fetch large awards, map to tickers, threshold, and de-duplicate clusters."""
    from downloaders.gov_contracts import fetch_large_awards_by_vendor

    raw = fetch_large_awards_by_vendor(list(vendor_ticker_map.values()), start, end)
    if raw.is_empty():
        return pl.DataFrame()

    v2t = {v: k for k, v in vendor_ticker_map.items()}
    df = raw.with_columns(
        pl.col("vendor").replace_strict(v2t, default=None).alias("symbol"),
        pl.col("action_date").str.slice(0, 10).str.strptime(pl.Date, strict=False)
        .alias("event_date"),
    ).drop_nulls(subset=["symbol", "event_date"]).filter(pl.col("amount") >= min_award)

    if df.is_empty():
        return df

    # Collapse near-duplicate events (modifications to the same award land within
    # days of each other): keep the largest within a `cluster_days` window per
    # symbol so a single program isn't counted as many events.
    df = df.sort(["symbol", "event_date", "amount"], descending=[False, False, True])
    kept = []
    last_date: dict[str, object] = {}
    for row in df.iter_rows(named=True):
        s, d = row["symbol"], row["event_date"]
        prev = last_date.get(s)
        if prev is None or (d - prev).days > cluster_days:
            kept.append(row)
            last_date[s] = d
    return pl.DataFrame(kept).select(["symbol", "event_date", "amount", "award_id"])


def run_study(output_dir="reports/contract_award_events", lookback_years=8,
              min_award=50e6, pre=5, post=60, cluster_days=7, universe=None):
    universe = universe or DEFENSE_UNIVERSE
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=lookback_years * 365)).strftime("%Y-%m-%d")

    logger.info("STEP 1: Building large-award events (%d names, >= $%.0fM, cluster=%dd)",
                len(universe), min_award / 1e6, cluster_days)
    events = build_events(universe, start, end, min_award, cluster_days=cluster_days)
    if events.is_empty():
        logger.error("No events built")
        return
    logger.info("Events: %d across %d symbols (%s → %s)",
                events.height, events["symbol"].n_unique(),
                events["event_date"].min(), events["event_date"].max())

    logger.info("STEP 2: Loading price data")
    bars = get_price_data(list(universe.keys()), start, end)
    if bars.is_empty():
        logger.error("No price data")
        return
    bars = bars.filter(pl.col("symbol") != SECTOR_ETF)

    logger.info("STEP 3: Running event study (window [-%d, +%d])", pre, post)
    study = EventStudy(bars, events, pre=pre, post=post)
    res = study.run()

    # ── Persist ────────────────────────────────────────────────────
    pl.DataFrame({"rel_day": res["rel_days"], "caar_pct": res["caar"],
                  "aar_pct": res["aar"]}).write_csv(out / "caar.csv")
    (out / "event_study.json").write_text(json.dumps(
        {k: v for k, v in res.items() if k not in ("aar", "caar", "rel_days")},
        indent=2, default=str))

    lines = [
        "# Contract Award — Event Study",
        "",
        f"**Events:** {res['n_events']} large awards (≥ ${min_award/1e6:.0f}M), "
        f"defense universe, vs {SECTOR_ETF}.",
        f"**Window:** [−{pre}, +{post}] trading days. CAR = cumulative abnormal "
        "return (stock − sector ETF).",
        "",
        "## CAR by window",
        "",
        "| window | n | mean CAR | t-stat | hit rate |",
        "|--------|--:|---------:|-------:|---------:|",
    ]
    for w in res["windows"].values():
        lines.append(f"| {w['window']} | {w['n']} | {w['mean_car_pct']:+.3f}% | "
                     f"{w['t_stat']:+.2f} | {w['hit_rate_pct']:.0f}% |")
    if res.get("size_buckets"):
        lines += ["", "## Post-event drift [1,20] by award size", "",
                  "| size | n | mean CAR | t-stat | hit rate |",
                  "|------|--:|---------:|-------:|---------:|"]
        for label, w in res["size_buckets"].items():
            lines.append(f"| {label} | {w['n']} | {w['mean_car_pct']:+.3f}% | "
                         f"{w['t_stat']:+.2f} | {w['hit_rate_pct']:.0f}% |")
    lines += ["", "_CAAR curve in `caar.csv`. Post-event windows [+1,…] are the",
              "tradeable part; [−5,−1] is descriptive run-up._"]
    (out / "summary.md").write_text("\n".join(lines) + "\n")

    logger.info("Report saved to %s/", out)
    for w in res["windows"].values():
        logger.info("  CAR %s: mean=%+.3f%% t=%+.2f (n=%d)",
                    w["window"], w["mean_car_pct"], w["t_stat"], w["n"])
    return res


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Contract Award — Event Study")
    p.add_argument("--years", type=int, default=8)
    p.add_argument("--out", default="reports/contract_award_events")
    p.add_argument("--min-award", type=float, default=50e6, help="Min award $ (default 50M)")
    p.add_argument("--pre", type=int, default=5)
    p.add_argument("--post", type=int, default=60)
    p.add_argument("--cluster-days", type=int, default=7,
                   help="Min calendar-day spacing between a symbol's events "
                        "(raise to ~90 for near-independent 60d windows)")
    p.add_argument("--universe", choices=list(UNIVERSES), default="defense")
    a = p.parse_args()
    run_study(a.out, a.years, a.min_award, a.pre, a.post, a.cluster_days,
              universe=UNIVERSES[a.universe])
