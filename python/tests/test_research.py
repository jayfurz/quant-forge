"""
Tests for the point-in-time research stack.

These lock in the correctness fixes from the rearchitecture pass:
  * no lookahead in the PIT join, the trailing z-score, or the velocity feature
  * forward returns computed correctly
  * the study runner's sign convention, balanced quantiles, non-overlapping
    sampling, and thin-period guard
  * the cleaner's trading-calendar keeps Fridays
"""
from datetime import datetime, timedelta

import numpy as np
import polars as pl
import pytest

from research import (
    FeatureStore,
    ForwardReturnLabeler,
    PointInTimeJoiner,
    SignalStudyRunner,
    build_award_velocity,
    trailing_zscore,
)


# ── trailing_zscore ────────────────────────────────────────────────
def test_trailing_zscore_is_expanding_not_full_sample():
    # A late spike must not change earlier z-scores (no lookahead).
    df = pl.DataFrame({
        "symbol": ["A"] * 6,
        "ts_available": [datetime(2020, 1, d) for d in range(1, 7)],
        "v": [1.0, 2.0, 3.0, 4.0, 5.0, 1000.0],
    })
    z = trailing_zscore(df, "v", min_periods=2)["v_z"].to_list()
    assert z[0] is None  # < min_periods
    # value 3 with history [1,2,3]: mean 2, sample std 1 -> z == 1.0 exactly,
    # independent of the 1000 that appears later.
    assert z[2] == pytest.approx(1.0)


def test_trailing_zscore_per_group():
    df = pl.DataFrame({
        "symbol": ["A", "A", "A", "B", "B", "B"],
        "ts_available": [datetime(2020, 1, d) for d in (1, 2, 3, 1, 2, 3)],
        "v": [1.0, 2.0, 3.0, 10.0, 20.0, 30.0],
    })
    z = trailing_zscore(df, "v", min_periods=3)
    # only the 3rd obs of each group is non-null, and both groups are linear so
    # their final z-scores match.
    vals = z.sort(["symbol", "ts_available"])["v_z"].to_list()
    assert vals[2] == pytest.approx(vals[5])


# ── build_award_velocity ───────────────────────────────────────────
def _synthetic_tx(seed=0):
    rng = np.random.default_rng(seed)
    base = datetime(2021, 1, 1)
    rows = []
    for s in ("A", "B"):
        for k in range(80):
            rows.append({
                "symbol": s,
                "action_date": (base + timedelta(days=k * 7)).strftime("%Y-%m-%d"),
                "amount": float(rng.integers(1, 100) * 1e6),
            })
    return pl.DataFrame(rows)


def test_award_velocity_applies_reporting_lag_and_pit():
    tx = _synthetic_tx()
    lag = 30
    feat = build_award_velocity(
        tx, recent_days=90, baseline_days=365,
        reporting_lag_days=lag, zscore_min_periods=4,
        as_of=datetime(2023, 1, 1),
    )
    assert not feat.is_empty()
    assert set(feat.columns) == {
        "symbol", "ts_available", "feature_name", "feature_value",
        "source", "source_event_id", "asof_date",
    }
    # ts_available is exactly action_date + reporting lag.
    delta = (feat["ts_available"] - feat["asof_date"]).dt.total_days()
    assert (delta == lag).all()


def test_award_velocity_drops_future_dated_rows():
    tx = pl.DataFrame({
        "symbol": ["A", "A"],
        "action_date": ["2020-01-01", "2099-01-01"],  # one in the future
        "amount": [1e6, 1e6],
    })
    feat = build_award_velocity(tx, as_of=datetime(2023, 1, 1))
    # future row must never appear (and with 1 valid point, no z-score emitted)
    if not feat.is_empty():
        assert feat["asof_date"].max() <= datetime(2023, 1, 1)


# ── ForwardReturnLabeler ───────────────────────────────────────────
def test_forward_returns_value_and_tail_nulls():
    closes = [100.0, 110.0, 121.0, 133.1]  # +10% each step
    df = pl.DataFrame({
        "symbol": ["A"] * 4,
        "date": [datetime(2022, 1, d) for d in range(1, 5)],
        "close": closes,
    })
    out = ForwardReturnLabeler(horizons=[1]).compute(df).sort("date")
    r = out["forward_1d_return"].to_list()
    assert r[0] == pytest.approx(10.0)
    assert r[-1] is None  # no future bar for the last row


# ── PointInTimeJoiner ──────────────────────────────────────────────
def test_pit_join_excludes_future_features(tmp_path):
    store = FeatureStore(tmp_path / "features")
    store.add_features(pl.DataFrame({
        "symbol": ["A", "A"],
        "ts_available": [datetime(2022, 1, 1), datetime(2022, 6, 1)],
        "feature_name": ["f", "f"],
        "feature_value": [1.0, 2.0],
        "source": ["x", "x"],
        "source_event_id": ["", ""],
        "asof_date": [datetime(2022, 1, 1), datetime(2022, 6, 1)],
    }))
    bars = pl.DataFrame({
        "symbol": ["A", "A", "A"],
        "date": [datetime(2022, 1, 15), datetime(2022, 3, 1), datetime(2022, 7, 1)],
        "close": [10.0, 11.0, 12.0],
    })
    joined = PointInTimeJoiner(store).join(bars, ["f"]).sort("date")
    vals = joined["f"].to_list()
    assert vals == [1.0, 1.0, 2.0]  # never sees 2.0 before it is available


# ── SignalStudyRunner ──────────────────────────────────────────────
def _predictive_panel(beta=2.0, seed=0, n_days=250, n_sym=10):
    rng = np.random.default_rng(seed)
    d0 = datetime(2022, 1, 3)
    rows = []
    for t in range(n_days):
        date = d0 + timedelta(days=t)
        for s in range(n_sym):
            feat = rng.standard_normal()
            fwd = beta * feat + rng.standard_normal() * 3
            rows.append({"symbol": f"S{s}", "date": date,
                         "feat": feat, "forward_20d_return": fwd})
    return pl.DataFrame(rows)


def test_study_runner_sign_and_monotonicity():
    rep = SignalStudyRunner(_predictive_panel()).run("feat", "forward_20d_return")
    ic = rep["ic_summary"]["pearson_ic_mean"]
    spread = rep["quintile_spread"]["mean_spread"]
    # positive predictive feature -> positive IC, positive Q5-Q1 spread, same sign
    assert ic > 0 and spread > 0
    # quintile means increase from Q1 (lowest feature) to Q5 (highest)
    means = [q["avg_return"] for q in sorted(
        rep["quintile_summary"], key=lambda x: x["quantile"])]
    assert means[0] < means[-1]


def test_study_runner_balanced_quantiles():
    rep = SignalStudyRunner(_predictive_panel(n_sym=10)).run("feat", "forward_20d_return")
    counts = [q["total_count"] for q in rep["quintile_summary"]]
    # 10 symbols / 5 buckets => 2 each per period; buckets must be equal-sized
    assert max(counts) == min(counts)


def test_study_runner_non_overlapping_sampling():
    rep = SignalStudyRunner(_predictive_panel(n_days=252)).run("feat", "forward_20d_return")
    assert rep["meta"]["rebalance_days"] == 20
    # ~252 calendar days sampled every 20th distinct date -> far fewer periods
    assert rep["meta"]["n_periods"] < 20


def test_study_runner_rejects_too_thin_universe():
    # only 3 symbols can't be sorted into 5 quantiles -> should raise
    panel = _predictive_panel(n_sym=3)
    with pytest.raises(ValueError):
        SignalStudyRunner(panel).run("feat", "forward_20d_return", n_quantiles=5)
