"""
ForwardReturnLabeler — compute forward returns for signal research.

Given OHLCV data (bars), computes the forward return over specified
horizons. The forward return is the percentage change from the close
on the reference date to the close N trading days later.

This is what we're trying to predict — the target variable in the
signal study.
"""

import logging
from typing import Optional

import polars as pl

logger = logging.getLogger(__name__)


class ForwardReturnLabeler:
    """
    Computes forward returns over multiple horizons.

    For each bar date, computes:
        forward_{N}d_return = (close_{t+N} - close_t) / close_t

    Forward returns are point-in-time safe because they look forward
    from the bar date — the label is computed from future prices,
    but the feature is only joined to past information.
    """

    DEFAULT_HORIZONS = [5, 10, 20, 40, 60, 120]

    def __init__(self, horizons: Optional[list[int]] = None):
        self.horizons = horizons or self.DEFAULT_HORIZONS

    def compute(
        self,
        bars: pl.DataFrame,
        date_col: str = "date",
        close_col: str = "close",
        symbol_col: str = "symbol",
    ) -> pl.DataFrame:
        """
        Add forward return columns to bars.

        Args:
            bars: DataFrame with [symbol, date, close]
            date_col: Name of date column
            close_col: Name of close price column
            symbol_col: Name of symbol column

        Returns:
            DataFrame with added columns: forward_{N}d_return,
            forward_{N}d_available (date of the forward close).
            Also adds benchmark_return if 'benchmark_close' column exists.
        """
        required = [symbol_col, date_col, close_col]
        missing = [c for c in required if c not in bars.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        result = bars.sort([symbol_col, date_col])

        for horizon in self.horizons:
            col_name = f"forward_{horizon}d_return"

            # Per symbol: shift close back by N and compute return
            result = result.with_columns([
                pl.col(close_col)
                .shift(-horizon)
                .over(symbol_col)
                .alias(f"_future_close_{horizon}"),
                pl.col(date_col)
                .shift(-horizon)
                .over(symbol_col)
                .alias(f"_future_date_{horizon}"),
            ])

            result = result.with_columns(
                ((pl.col(f"_future_close_{horizon}") - pl.col(close_col))
                 / pl.col(close_col) * 100.0)
                .alias(col_name)
            )

            # Forward return is null if we don't have future data
            # (naturally handled by shift producing nulls at the end)

        # Compute benchmark-relative returns if benchmark column exists
        if "benchmark_close" in result.columns:
            for horizon in self.horizons:
                col_name = f"forward_{horizon}d_excess"
                result = result.with_columns([
                    pl.col("benchmark_close")
                    .shift(-horizon)
                    .over(symbol_col)
                    .alias(f"_bm_future_{horizon}"),
                ])
                result = result.with_columns(
                    ((pl.col(f"_future_close_{horizon}") - pl.col(close_col))
                     / pl.col(close_col) * 100.0
                     - (pl.col(f"_bm_future_{horizon}") - pl.col("benchmark_close"))
                     / pl.col("benchmark_close") * 100.0)
                    .alias(col_name)
                )

        # Drop temporary columns
        drop_cols = [c for c in result.columns
                     if c.startswith("_future_") or c.startswith("_bm_future_")]
        result = result.drop(drop_cols)

        return result

    @staticmethod
    def horizons_info(horizons: list[int]) -> str:
        """Human-readable horizon descriptions."""
        return ", ".join(f"{h}d" for h in horizons)
