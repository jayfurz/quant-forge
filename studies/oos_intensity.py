#!/usr/bin/env python3
"""
Out-of-sample validation of the contract_intensity signal.

v6 found size-relative contract intensity significant in-sample (20d
Fama–MacBeth t≈2.1 on the wide universe). "Promising, not proven" — so here we
check it the only way that matters: does it hold on data the in-sample fit never
saw?

Two disjoint splits, each re-running the full multivariate Fama–MacBeth
(forward ~ velocity + intensity + momentum):
  1. TEMPORAL: first half of the dates vs second half (true holdout in time).
  2. UNIVERSE: even-indexed vs odd-indexed tickers (is it broad, or a few names?).

Reuses contract_award_velocity.assemble_panel so feature definitions are
identical to the headline study, and reads cached prices/features (run the wide
study first to populate them).

Usage:
    python studies/oos_intensity.py
"""

import json
import logging
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from research import FeatureStore, fama_macbeth  # noqa: E402
from contract_award_velocity import (  # noqa: E402
    WIDE_UNIVERSE, SECTOR_ETF, assemble_panel,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

FEATURES = ["contract_award_velocity_z", "contract_intensity", "price_momentum_63d"]


def load_cached_bars(universe: dict) -> pl.DataFrame:
    """Rebuild the bars panel (incl. benchmark_close) from cached Yahoo CSVs."""
    md = Path("data/market_data")
    frames = []
    for sym in list(universe) + [SECTOR_ETF]:
        p = md / f"{sym}_1d.csv"
        if not p.exists():
            continue
        df = pl.read_csv(p, try_parse_dates=True).with_columns(pl.lit(sym).alias("symbol"))
        frames.append(df.rename({"ts": "date"}).select(
            ["symbol", "date", "open", "high", "low", "close", "volume"]))
    if not frames:
        raise SystemExit("No cached price data — run the wide study first.")
    bars = pl.concat(frames).sort(["symbol", "date"])
    bm = bars.filter(pl.col("symbol") == SECTOR_ETF).select(
        ["date", pl.col("close").alias("benchmark_close")])
    return bars.join(bm, on="date", how="left").filter(pl.col("symbol") != SECTOR_ETF)


def _fm_row(panel: pl.DataFrame, horizon: int) -> dict:
    res = fama_macbeth(panel, FEATURES, forward_col=f"forward_{horizon}d_return")
    c = res["coefficients"]
    return {
        "n_periods": res["n_periods"],
        **{f: {"b": round(c[f]["mean"], 3), "t": round(c[f]["t_stat"], 2)} for f in FEATURES},
    }


def run(out_dir="reports/oos_intensity", horizons=(20, 60)):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    store = FeatureStore("data/features/contract_award_velocity_wide")
    if not store.feature_names():
        raise SystemExit("No cached features — run: contract_award_velocity.py "
                         "--universe wide --out reports/contract_award_velocity_wide")
    bars = load_cached_bars(WIDE_UNIVERSE)
    panel, _ = assemble_panel(bars, store, list(horizons))
    panel = panel.drop_nulls(subset=FEATURES + [f"forward_{h}d_return" for h in horizons])

    results = {"full": {}, "temporal": {}, "universe": {}}

    # Full (reference)
    for h in horizons:
        results["full"][f"{h}d"] = _fm_row(panel, h)

    # 1. Temporal split at the median date.
    dates = panel["date"].unique().sort()
    mid = dates[len(dates) // 2]
    first = panel.filter(pl.col("date") < mid)
    second = panel.filter(pl.col("date") >= mid)
    logger.info("Temporal split @ %s: %d vs %d rows", mid, first.height, second.height)
    for label, part in (("in_sample_first_half", first), ("oos_second_half", second)):
        results["temporal"][label] = {f"{h}d": _fm_row(part, h) for h in horizons}

    # 2. Universe split (even/odd tickers, deterministic).
    syms = sorted(panel["symbol"].unique().to_list())
    a = set(syms[::2])
    b = set(syms[1::2])
    pa = panel.filter(pl.col("symbol").is_in(list(a)))
    pb = panel.filter(pl.col("symbol").is_in(list(b)))
    logger.info("Universe split: %d vs %d symbols", len(a), len(b))
    for label, part in (("universe_A", pa), ("universe_B", pb)):
        results["universe"][label] = {f"{h}d": _fm_row(part, h) for h in horizons}

    (out / "oos.json").write_text(json.dumps(results, indent=2))
    _write_md(out / "summary.md", results, horizons)

    # console summary: the intensity t-stat is what we care about
    logger.info("=== contract_intensity Fama-MacBeth t-stats ===")
    def it(d, h): return d[f"{h}d"]["contract_intensity"]["t"]
    for h in horizons:
        logger.info("  %dd | full=%+.2f | IS(1st half)=%+.2f OOS(2nd half)=%+.2f | "
                    "univ_A=%+.2f univ_B=%+.2f", h,
                    it(results["full"], h),
                    it(results["temporal"]["in_sample_first_half"], h),
                    it(results["temporal"]["oos_second_half"], h),
                    it(results["universe"]["universe_A"], h),
                    it(results["universe"]["universe_B"], h))
    return results


def _write_md(path, results, horizons):
    lines = ["# Out-of-sample validation — contract_intensity", "",
             "Fama–MacBeth `forward ~ velocity + intensity + momentum`. Each cell is",
             "the **intensity** coefficient t-stat (the signal under test).", "",
             "| split | " + " | ".join(f"{h}d" for h in horizons) + " |",
             "|---|" + "|".join(["---"] * len(horizons)) + "|"]

    def row(label, d):
        cells = [f"t={d[f'{h}d']['contract_intensity']['t']:+.2f} "
                 f"(n={d[f'{h}d']['n_periods']})" for h in horizons]
        return f"| {label} | " + " | ".join(cells) + " |"

    lines.append(row("full sample", results["full"]))
    lines.append(row("in-sample (1st half)", results["temporal"]["in_sample_first_half"]))
    lines.append(row("**OOS (2nd half)**", results["temporal"]["oos_second_half"]))
    lines.append(row("universe A (even)", results["universe"]["universe_A"]))
    lines.append(row("universe B (odd)", results["universe"]["universe_B"]))
    lines += ["", "_Each split halves the data, so t-stats shrink with √n; look for",
              "consistent sign/magnitude, not |t|>2 in every cell._"]
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    run()
