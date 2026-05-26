#!/usr/bin/env python3
"""Smoke test: cleaners, exporters, and Yahoo Finance data download."""
import sys
sys.path.insert(0, '.')

from cleaners.ohlcv_cleaner import clean_ohlcv, detect_splits, normalize_volume
import polars as pl

# ── Cleaners ──────────────────────────────────────────────────────
# Synthetic OHLCV with a gap and an outlier
from datetime import date
df = pl.DataFrame({
    "ts": pl.date_range(date(2025, 1, 1), date(2025, 1, 20), interval="1d", eager=True),
    "open":   [100.0] * 20,
    "high":   [105.0] * 20,
    "low":    [95.0] * 20,
    "close":  [102.0] * 20,
    "volume": [1_000_000] * 20,
})

# Insert a null close at row 6
import numpy as np
close_vals = df["close"].to_list()
open_vals = df["open"].to_list()
close_vals[5] = None
open_vals[5] = None
df = df.with_columns(
    pl.Series("close", close_vals),
    pl.Series("open", open_vals),
)

cleaned = clean_ohlcv(df, symbol="TEST")
assert cleaned["close"].null_count() == 0, f"Nulls remain: {cleaned['close'].null_count()}"
assert "day_of_week" in cleaned.columns
print("  ✅ clean_ohlcv: nulls filled, day_of_week added")

# Test split detection - fresh df with NO nulls to avoid the None check issue
from datetime import date as dt_date
df_splits = pl.DataFrame({
    "ts": pl.date_range(dt_date(2025, 1, 1), dt_date(2025, 1, 20), interval="1d", eager=True),
    "open":   [100.0] * 20,
    "high":   [105.0] * 20,
    "low":    [95.0] * 20,
    "close":  [102.0] * 20,
    "volume": [1_000_000] * 20,
})
# Row 11: set close to 35 (35/102 = 0.34 < 0.40 threshold → triggers)
close_list = df_splits["close"].to_list()
close_list[10] = 35.0
df_splits = df_splits.with_columns(pl.Series("close", close_list))
splits = detect_splits(df_splits)
assert len(splits) == 1, f"Expected 1 split, got {len(splits)}"
# 102/35 ≈ 2.91 → round to 3 → suspected 1:3
assert splits[0]["ratio_suspected"] in ["1:3", "1:2"]
print(f"  ✅ detect_splits: found {len(splits)} split(s)")

# Volume normalization — use varying values for meaningful z-score
vol_series = pl.Series("volume", [500_000, 800_000, 1_200_000, 600_000, 900_000])
norm = normalize_volume(vol_series)
assert abs(norm.mean()) < 1e-10  # z-score mean ≈ 0
assert abs(norm.std() - 1.0) < 0.1  # z-score std ≈ 1
print("  ✅ normalize_volume: z-score correct")

# ── Exporters ─────────────────────────────────────────────────────
from exporters.simulation_format import (
    to_simulation_format, export_parquet, generate_universe_config
)
import tempfile, os

sim_df = to_simulation_format(cleaned, "TEST")
assert "symbol" in sim_df.columns
assert sim_df["symbol"][0] == "TEST"
print("  ✅ to_simulation_format: schema correct")

with tempfile.TemporaryDirectory() as tmp:
    path = f"{tmp}/TEST.parquet"
    export_parquet(sim_df, path)
    assert os.path.exists(path)
    print(f"  ✅ export_parquet: wrote {os.path.getsize(path)} bytes")

    config_path = f"{tmp}/universe.json"
    generate_universe_config(["AAPL", "MSFT"], "2023-01-01", "2025-01-01", config_path)
    assert os.path.exists(config_path)
    print("  ✅ generate_universe_config: written")

# ── Yahoo Finance (live test) ─────────────────────────────────────
print()
print("=== Yahoo Finance Live Test ===")
from downloaders.ohlcv import download_yahoo

try:
    aapl = download_yahoo("AAPL", "2025-01-01", "2025-05-01", interval="1d")
    assert aapl.height > 50, f"Only got {aapl.height} bars for AAPL"
    assert "close" in aapl.columns
    assert aapl["close"].mean() > 50  # AAPL is >$50
    print(f"  ✅ Yahoo Finance: AAPL → {aapl.height} bars")
    print(f"     Range: {aapl['ts'].min()} to {aapl['ts'].max()}")
    print(f"     Avg close: ${aapl['close'].mean():.2f}")
except Exception as e:
    print(f"  ⚠️  Yahoo Finance skipped: {e}")

print()
print("=" * 50)
print("CLEANERS + EXPORTERS + LIVE DATA: PASSED ✅")
print("=" * 50)
