"""Tests for OHLCV cleaning utilities."""
from datetime import datetime

import polars as pl

from cleaners.ohlcv_cleaner import align_to_trading_calendar


def test_trading_calendar_keeps_all_weekdays_including_friday():
    # Mon 2024-01-01 .. Sun 2024-01-07. Expect Mon-Fri (5 days), no weekend.
    df = pl.DataFrame({
        "ts": [datetime(2024, 1, 1), datetime(2024, 1, 5)],  # Monday, Friday
        "open": [1.0, 1.0], "high": [1.0, 1.0], "low": [1.0, 1.0],
        "close": [1.0, 1.0], "volume": [1, 1],
    })
    out = align_to_trading_calendar(df)
    weekdays = out["ts"].dt.weekday().to_list()
    assert 5 in weekdays, "Friday (weekday 5) must be kept"
    assert all(w <= 5 for w in weekdays), "no weekend days"
    assert len(weekdays) == 5
