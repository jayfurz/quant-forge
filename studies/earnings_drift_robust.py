#!/usr/bin/env python3
"""
Robustness gauntlet for the revenue-surprise *reversal* (studies/earnings_drift.py).

The naive event study showed accelerating-revenue large caps reverse down after
the report (pos [1,20] t=−2.06, neg [1,60] t=+2.84). Those cross-event t-stats
assume independence, but earnings cluster in seasons → inflated. We stress it:

  1. CALENDAR-CLUSTERED t: collapse events to one obs per event-month, t across
     months (the honest correction for season clustering).
  2. LONG/SHORT reversal P&L per event = −sign(surprise) · CAR  (positive ⇒ the
     reversal is real & directionally tradeable); naive + clustered t.
  3. LIQUIDITY split: reversal/overreaction should be stronger in less-liquid
     names → terciles by trailing dollar volume.
  4. OUT-OF-SAMPLE: first half vs second half of event dates.

Run earnings_drift.py / fundamental_momentum.py first (needs cached prices +
features).

Usage: python studies/earnings_drift_robust.py
"""

import json
import logging
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from research import EventStudy, FeatureStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BENCHMARK = "SPY"
WINDOWS = [(1, 20), (1, 60)]


def load_bars_with_volume() -> pl.DataFrame:
    frames = []
    for p in sorted(Path("data/market_data").glob("*_1d.csv")):
        sym = p.stem.split("_")[0]
        df = pl.read_csv(p, try_parse_dates=True).with_columns(pl.lit(sym).alias("symbol"))
        frames.append(df.rename({"ts": "date"}).select(
            ["symbol", "date", "close", "volume"]))
    bars = pl.concat(frames).sort(["symbol", "date"])
    bm = bars.filter(pl.col("symbol") == BENCHMARK).select(
        ["date", pl.col("close").alias("benchmark_close")])
    return bars.join(bm, on="date", how="left")


def _t(x: np.ndarray) -> tuple[float, float]:
    x = x[np.isfinite(x)]
    n = x.size
    if n < 2:
        return (float(x.mean()) if n else 0.0, 0.0)
    sd = x.std(ddof=1)
    return float(x.mean()), (float(x.mean() / (sd / np.sqrt(n))) if sd > 0 else 0.0)


def clustered(df: pl.DataFrame, col: str) -> dict:
    """Event-mean + naive t + calendar-clustered t (one obs per event-month)."""
    d = df.drop_nulls(col)
    mean, naive = _t(d[col].to_numpy())
    monthly = (d.with_columns((pl.col("event_date").dt.year() * 12
                               + pl.col("event_date").dt.month()).alias("_m"))
               .group_by("_m").agg(pl.col(col).mean().alias("m")))
    _, clus = _t(monthly["m"].to_numpy())
    return {"n": d.height, "n_months": monthly.height, "mean_pct": round(mean, 3),
            "naive_t": round(naive, 2), "clustered_t": round(clus, 2)}


def run(out_dir="reports/earnings_drift_robust", surprise="rev_yoy_accel"):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    bars = load_bars_with_volume()
    store = FeatureStore("data/features/fundamental_momentum")
    ev = store._load_feature(surprise)
    if ev is None:
        raise SystemExit("Run fundamental_momentum.py first.")
    events = ev.select(["symbol", pl.col("ts_available").dt.date().alias("event_date"),
                        pl.col("feature_value").alias("amount")])

    es = EventStudy(bars.select(["symbol", "date", "close", "benchmark_close"]),
                    events, pre=5, post=60)
    cars = es.event_cars(WINDOWS)  # symbol, event_date, amount, car_1_20, car_1_60

    # Trailing 63d avg dollar volume as a liquidity/size proxy, PIT (backward asof).
    dv = (bars.filter(pl.col("symbol") != BENCHMARK)
          .with_columns((pl.col("close") * pl.col("volume")).alias("_dv"))
          .with_columns(pl.col("_dv").rolling_mean_by("date", "63d").over("symbol")
                        .alias("dollar_vol")))
    cars = cars.with_columns(pl.col("event_date").cast(pl.Datetime("us")).alias("_d")).sort("_d")
    cars = cars.join_asof(
        dv.select(["symbol", pl.col("date").cast(pl.Datetime("us")).alias("_d"), "dollar_vol"]).sort("_d"),
        on="_d", by="symbol", strategy="backward").drop("_d")

    # Long/short reversal P&L per event: bet AGAINST the surprise sign.
    cars = cars.with_columns([
        (-np.sign(pl.col("amount")) * pl.col(f"car_{a}_{b}")).alias(f"ls_{a}_{b}")
        for a, b in WINDOWS
    ])
    pos = cars.filter(pl.col("amount") > 0)
    neg = cars.filter(pl.col("amount") < 0)

    report = {"groups": {}, "long_short": {}, "liquidity": {}, "oos": {}}

    # 1+2. Per-group and long/short, naive vs clustered.
    for a, b in WINDOWS:
        c = f"car_{a}_{b}"
        ls = f"ls_{a}_{b}"
        report["groups"][f"positive_{a}_{b}"] = clustered(pos, c)
        report["groups"][f"negative_{a}_{b}"] = clustered(neg, c)
        report["long_short"][f"{a}_{b}"] = clustered(cars, ls)

    # 3. Liquidity terciles on the long/short reversal P&L (1,60).
    liq = cars.drop_nulls("dollar_vol")
    q1, q2 = liq["dollar_vol"].quantile(1/3), liq["dollar_vol"].quantile(2/3)
    for label, expr in (("low_liquidity", pl.col("dollar_vol") <= q1),
                        ("mid_liquidity", (pl.col("dollar_vol") > q1) & (pl.col("dollar_vol") <= q2)),
                        ("high_liquidity", pl.col("dollar_vol") > q2)):
        report["liquidity"][label] = clustered(liq.filter(expr), "ls_1_60")

    # 4. Out-of-sample temporal split (median event date).
    mid = cars["event_date"].median()
    for label, part in (("first_half", cars.filter(pl.col("event_date") < mid)),
                        ("second_half", cars.filter(pl.col("event_date") >= mid))):
        report["oos"][label] = {"long_short_1_60": clustered(part, "ls_1_60"),
                                "long_short_1_20": clustered(part, "ls_1_20")}

    (out / "robustness.json").write_text(json.dumps(report, indent=2, default=str))
    _write_md(out / "summary.md", report)

    logger.info("=== naive vs calendar-clustered t ===")
    for k, v in report["groups"].items():
        logger.info("  %-16s mean=%+.3f%% naive_t=%+.2f clustered_t=%+.2f (n=%d, months=%d)",
                    k, v["mean_pct"], v["naive_t"], v["clustered_t"], v["n"], v["n_months"])
    for k, v in report["long_short"].items():
        logger.info("  LS %-13s mean=%+.3f%% naive_t=%+.2f clustered_t=%+.2f",
                    k, v["mean_pct"], v["naive_t"], v["clustered_t"])
    logger.info("=== liquidity (LS reversal, 1-60) ===")
    for k, v in report["liquidity"].items():
        logger.info("  %-16s mean=%+.3f%% clustered_t=%+.2f", k, v["mean_pct"], v["clustered_t"])
    logger.info("=== OOS (LS reversal) ===")
    for k, v in report["oos"].items():
        logger.info("  %-12s 1-60: mean=%+.3f%% clustered_t=%+.2f | 1-20: clustered_t=%+.2f",
                    k, v["long_short_1_60"]["mean_pct"], v["long_short_1_60"]["clustered_t"],
                    v["long_short_1_20"]["clustered_t"])
    logger.info("Reports → %s/", out)
    return report


def _row(d): return (f"{d['mean_pct']:+.3f}% | naive t={d['naive_t']:+.2f} | "
                     f"**clustered t={d['clustered_t']:+.2f}** | n={d['n']}, mo={d['n_months']}")


def _write_md(path, r):
    L = ["# Revenue-surprise reversal — robustness gauntlet", "",
         "Naive cross-event t-stats vs **calendar-clustered** (one obs per",
         "event-month) — the honest correction for earnings-season clustering.", "",
         "## Per group (CAR)", "", "| group/window | mean | naive t | clustered t | n |",
         "|---|--:|--:|--:|--:|"]
    for k, d in r["groups"].items():
        L.append(f"| {k} | {d['mean_pct']:+.3f}% | {d['naive_t']:+.2f} | "
                 f"{d['clustered_t']:+.2f} | {d['n']} ({d['n_months']}mo) |")
    L += ["", "## Long/short reversal P&L  (−sign(surprise)·CAR; >0 ⇒ reversal pays)",
          "", "| window | mean | naive t | clustered t |", "|---|--:|--:|--:|"]
    for k, d in r["long_short"].items():
        L.append(f"| {k} | {d['mean_pct']:+.3f}% | {d['naive_t']:+.2f} | {d['clustered_t']:+.2f} |")
    L += ["", "## Liquidity terciles (LS reversal, [1,60], clustered t)", "",
          "| tercile | mean | clustered t |", "|---|--:|--:|"]
    for k, d in r["liquidity"].items():
        L.append(f"| {k} | {d['mean_pct']:+.3f}% | {d['clustered_t']:+.2f} |")
    L += ["", "## Out-of-sample (LS reversal, clustered t)", "",
          "| half | [1,20] | [1,60] |", "|---|--:|--:|"]
    for k, d in r["oos"].items():
        L.append(f"| {k} | {d['long_short_1_20']['clustered_t']:+.2f} | "
                 f"{d['long_short_1_60']['clustered_t']:+.2f} |")
    L += ["", "_Clustered t is the one to trust. |t|≳2 in clustered AND out-of-sample",
          "would make the reversal credible._"]
    path.write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    run()
