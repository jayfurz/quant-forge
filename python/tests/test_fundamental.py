"""Tests for the fundamental-momentum feature builder."""
from datetime import date, timedelta

import polars as pl

from research import build_fundamental_momentum


def _rev_rows(symbol, fp, start_year, vals, file_lag_days=30):
    """One ~quarterly revenue row per year for a fixed fiscal period."""
    rows = []
    for i, v in enumerate(vals):
        end = date(start_year + i, 3, 31)
        start = end - timedelta(days=89)
        rows.append({
            "symbol": symbol, "start": start.isoformat(), "end": end.isoformat(),
            "val": float(v), "fy": start_year + i, "fp": fp,
            "filed": (end + timedelta(days=file_lag_days)).isoformat(), "form": "10-Q",
        })
    return rows


def test_yoy_growth_and_acceleration():
    # revenue 100 -> 110 -> 121 : +10% then +10% growth, accel 0 on the 3rd
    rows = _rev_rows("A", "Q1", 2020, [100, 110, 121])
    feat = build_fundamental_momentum(pl.DataFrame(rows))
    g = feat.filter(pl.col("feature_name") == "rev_yoy_growth").sort("ts_available")
    # first year has no prior -> dropped; next two are +10%
    assert g.height == 2
    assert g["feature_value"].to_list() == [pl.Series([10.0]).to_list()[0], 10.0] or \
        all(abs(x - 10.0) < 1e-6 for x in g["feature_value"].to_list())
    accel = feat.filter(pl.col("feature_name") == "rev_yoy_accel")
    assert accel.height == 1  # only the 3rd point has a defined acceleration
    assert abs(accel["feature_value"][0]) < 1e-6  # 10% - 10% = 0


def test_drops_annual_duration_rows():
    # a 365-day (annual) row must be filtered out; only the ~90d ones survive
    rows = _rev_rows("A", "Q1", 2020, [100, 110, 121])
    annual = {"symbol": "A", "start": "2022-01-01", "end": "2022-12-31",
              "val": 500.0, "fy": 2022, "fp": "FY", "filed": "2023-02-01", "form": "10-K"}
    feat = build_fundamental_momentum(pl.DataFrame(rows + [annual]))
    # the FY row contributes no Q1 series point
    assert set(feat["asof_date"].dt.year().to_list()) <= {2021, 2022}


def test_pit_keeps_first_filing_not_restatement():
    end = date(2021, 3, 31)
    start = end - timedelta(days=89)
    base = {"symbol": "A", "start": start.isoformat(), "end": end.isoformat(),
            "fy": 2021, "fp": "Q1", "form": "10-Q"}
    prior = {**base, "end": date(2020, 3, 31).isoformat(),
             "start": (date(2020, 3, 31) - timedelta(days=89)).isoformat(),
             "val": 100.0, "filed": "2020-04-30", "fy": 2020}
    original = {**base, "val": 120.0, "filed": "2021-04-30"}       # first: +20%
    restate = {**base, "val": 200.0, "filed": "2022-01-01"}        # later restatement
    feat = build_fundamental_momentum(pl.DataFrame([prior, original, restate]))
    g = feat.filter(pl.col("feature_name") == "rev_yoy_growth")
    assert g.height == 1
    assert abs(g["feature_value"][0] - 20.0) < 1e-6  # uses 120, not the 200 restatement
