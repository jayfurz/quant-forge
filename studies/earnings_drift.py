#!/usr/bin/env python3
"""
Post-Earnings / Revenue-Surprise Drift — Event Study (PEAD)

The cross-sectional fundamental_momentum study found no slow-factor edge. PEAD,
the documented effect, is event-time: stocks DRIFT after an earnings surprise.
Here we test it directly — events are quarterly revenue reports, the "surprise"
is revenue YoY acceleration (accelerating = good news), and we measure abnormal
return (stock − SPY) after the report for positive vs negative surprises.

Event date = the SEC `filed` date (point-in-time public). Caveat: the 10-Q
filing lags the earnings *announcement*, so this captures the post-filing tail
of any drift, a conservative lower bound on the announcement-date effect.

Reuses research.EventStudy. Run fundamental_momentum.py first to populate the
feature store + price cache.

Usage:
    python studies/earnings_drift.py
"""

import json
import logging
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from research import EventStudy, FeatureStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BENCHMARK = "SPY"


def load_bars() -> pl.DataFrame:
    md = Path("data/market_data")
    frames = []
    for p in sorted(md.glob("*_1d.csv")):
        sym = p.stem.split("_")[0]
        df = pl.read_csv(p, try_parse_dates=True).with_columns(pl.lit(sym).alias("symbol"))
        frames.append(df.rename({"ts": "date"}).select(
            ["symbol", "date", "close"]))
    bars = pl.concat(frames).sort(["symbol", "date"])
    bm = bars.filter(pl.col("symbol") == BENCHMARK).select(
        ["date", pl.col("close").alias("benchmark_close")])
    return bars.join(bm, on="date", how="left").filter(pl.col("symbol") != BENCHMARK)


def load_events(feature="rev_yoy_accel") -> pl.DataFrame:
    store = FeatureStore("data/features/fundamental_momentum")
    df = store._load_feature(feature)
    if df is None:
        raise SystemExit("No fundamental features — run fundamental_momentum.py first.")
    return df.select([
        "symbol",
        pl.col("ts_available").dt.date().alias("event_date"),
        pl.col("feature_value").alias("amount"),  # the surprise magnitude/sign
    ])


def _windows_md(title, res):
    lines = [f"### {title} (n={res['n_events']})", "",
             "| window | n | mean CAR | t-stat | hit |",
             "|---|--:|--:|--:|--:|"]
    for w in res["windows"].values():
        lines.append(f"| {w['window']} | {w['n']} | {w['mean_car_pct']:+.3f}% | "
                     f"{w['t_stat']:+.2f} | {w['hit_rate_pct']:.0f}% |")
    return lines


def run(out_dir="reports/earnings_drift", pre=5, post=60, surprise="rev_yoy_accel"):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    bars = load_bars()
    events = load_events(surprise)
    pos = events.filter(pl.col("amount") > 0)
    neg = events.filter(pl.col("amount") < 0)
    logger.info("Events: %d total (%d positive, %d negative surprises) on %s",
                events.height, pos.height, neg.height, surprise)

    res_all = EventStudy(bars, events, pre=pre, post=post).run()
    res_pos = EventStudy(bars, pos, pre=pre, post=post).run()
    res_neg = EventStudy(bars, neg, pre=pre, post=post).run()

    out_json = {"all": {k: v for k, v in res_all.items() if k in ("n_events", "windows")},
                "positive": {k: v for k, v in res_pos.items() if k in ("n_events", "windows")},
                "negative": {k: v for k, v in res_neg.items() if k in ("n_events", "windows")}}
    (out / "event_study.json").write_text(json.dumps(out_json, indent=2, default=str))
    pl.DataFrame({"rel_day": res_pos["rel_days"],
                  "caar_positive": res_pos["caar"],
                  "caar_negative": res_neg["caar"]}).write_csv(out / "caar.csv")

    lines = ["# Revenue-Surprise Drift (PEAD) — Event Study", "",
             f"Surprise = `{surprise}` (revenue YoY acceleration). Abnormal return "
             f"vs {BENCHMARK}, window [−{pre}, +{post}]. Event = SEC filing date.", ""]
    lines += _windows_md("Positive surprises (accel > 0)", res_pos) + [""]
    lines += _windows_md("Negative surprises (accel < 0)", res_neg) + [""]
    lines += _windows_md("All events", res_all) + [""]
    # long/short read-across
    def car(res, w): return res["windows"].get(w, {}).get("mean_car_pct", 0.0)
    lines += ["## Positive − Negative drift (read-across)", "",
              "| window | pos CAR | neg CAR | spread |", "|---|--:|--:|--:|"]
    for w in res_pos["windows"]:
        lines.append(f"| {w} | {car(res_pos, w):+.3f}% | {car(res_neg, w):+.3f}% | "
                     f"{car(res_pos, w) - car(res_neg, w):+.3f}% |")
    lines += ["", "_Quarterly events ~63 trading days apart, so 60d windows barely",
              "overlap within a name (unlike the contract event study). t-stats are",
              "cross-event; calendar clustering across names remains, mitigated by",
              "the SPY adjustment. Filing date lags the announcement → lower bound._"]
    (out / "summary.md").write_text("\n".join(lines) + "\n")

    logger.info("=== PEAD drift (pos vs neg), CAR mean%% ===")
    for w in res_pos["windows"]:
        logger.info("  %-8s pos=%+.3f%% (t=%+.2f) | neg=%+.3f%% (t=%+.2f) | spread=%+.3f%%",
                    w, car(res_pos, w), res_pos["windows"][w]["t_stat"],
                    car(res_neg, w), res_neg["windows"][w]["t_stat"],
                    car(res_pos, w) - car(res_neg, w))
    logger.info("Reports → %s/", out)
    return out_json


if __name__ == "__main__":
    run()
