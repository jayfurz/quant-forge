"""Tests for the EventStudy engine."""
from datetime import datetime, timedelta

import numpy as np
import polars as pl

from research import EventStudy


def _bars_with_drift(n_days=400, n_sym=6, drift_after=None, drift_bps=50, seed=0):
    """
    Build bars where, if drift_after is given, each symbol gets a fixed positive
    abnormal return on the 5 trading days AFTER its event day (relative +1..+5).
    Benchmark is flat-ish noise shared across symbols.
    """
    rng = np.random.default_rng(seed)
    d0 = datetime(2020, 1, 1)
    dates = [d0 + timedelta(days=i) for i in range(n_days)]
    bench = 100 * np.cumprod(1 + rng.standard_normal(n_days) * 0.005)
    rows = []
    events = []
    for s in range(n_sym):
        ev_idx = 100 + s * 30  # distinct event positions
        events.append({"symbol": f"S{s}", "event_date": dates[ev_idx], "amount": 1e8 * (s + 1)})
        # daily abnormal (idiosyncratic) returns; inject drift on +1..+5
        ar = rng.standard_normal(n_days) * 0.003
        if drift_after:
            ar[ev_idx + 1: ev_idx + 6] += drift_bps / 1e4
        # stock return = benchmark return + abnormal
        br = np.diff(bench, prepend=bench[0]) / bench
        sr = br + ar
        px = 100 * np.cumprod(1 + sr)
        for i, dt in enumerate(dates):
            rows.append({"symbol": f"S{s}", "date": dt, "close": px[i],
                         "benchmark_close": bench[i]})
    return pl.DataFrame(rows), pl.DataFrame(events)


def test_event_study_detects_post_event_drift():
    bars, events = _bars_with_drift(drift_after=True, drift_bps=80)
    res = EventStudy(bars, events, pre=5, post=20).run()
    assert res["n_events"] == 6
    car = res["windows"]["[1,5]"]
    # ~5 days * 80bps = ~4% cumulative abnormal return, strongly positive
    assert car["mean_car_pct"] > 2.0
    assert car["hit_rate_pct"] == 100.0


def test_event_study_flat_when_no_drift():
    bars, events = _bars_with_drift(drift_after=False)
    res = EventStudy(bars, events, pre=5, post=20).run()
    # no injected drift -> small CAR, not large
    assert abs(res["windows"]["[1,5]"]["mean_car_pct"]) < 2.0


def test_event_study_caar_length_matches_window():
    bars, events = _bars_with_drift(drift_after=True)
    res = EventStudy(bars, events, pre=5, post=20).run()
    assert len(res["caar"]) == len(res["rel_days"]) == 26  # -5..+20
