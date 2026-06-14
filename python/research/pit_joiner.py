"""
PointInTimeJoiner — strict temporal alignment of bars and features.

Given a bars DataFrame (close prices with dates) and a FeatureStore,
returns a joined DataFrame where each bar date is matched to the
most recent feature value available BEFORE that date.

This is the gate that prevents lookahead bias. If a feature's
ts_available is after the bar date, it is NOT included.
"""

import logging
from datetime import datetime
from typing import Optional

import polars as pl

from .feature_store import FeatureStore

logger = logging.getLogger(__name__)


class PointInTimeJoiner:
    """
    Joins bars to features with strict point-in-time enforcement.

    For each (symbol, bar_date) pair, finds the latest feature value
    where ts_available <= bar_date. Features that become available
    AFTER the bar date are excluded — no lookahead.
    """

    def __init__(self, store: FeatureStore):
        self.store = store

    def join(
        self,
        bars: pl.DataFrame,
        feature_names: Optional[list[str]] = None,
        bar_date_col: str = "date",
    ) -> pl.DataFrame:
        """
        Join bars to point-in-time features.

        Args:
            bars: DataFrame with at least [symbol, date_col, close]
            feature_names: Which features to join (None = all)
            bar_date_col: Name of the date column in bars

        Returns:
            DataFrame with bars + feature columns, one row per (symbol, date).
            Feature columns will be null if no data available at that date.
        """
        required = ["symbol", bar_date_col]
        missing = [c for c in required if c not in bars.columns]
        if missing:
            raise ValueError(f"Bars missing required columns: {missing}")

        names = feature_names or self.store.feature_names()
        if not names:
            logger.warning("No features in store, returning bars unchanged")
            return bars.clone()

        # Get all features available up to the last bar. We must NOT lower-bound
        # by the first bar date: a feature that became available *before* the
        # first bar is still the valid carry-forward value for that bar, and
        # clipping it out would leave early bars spuriously null.
        symbols = bars["symbol"].unique().to_list()
        max_date = bars[bar_date_col].max()
        epoch = datetime(1900, 1, 1)

        features = self.store.query_range(symbols, names, epoch, max_date)

        if features.is_empty():
            logger.warning("No features found in date range, returning bars unchanged")
            return bars.clone()

        # For each feature, we need to asof-join: for each (symbol, bar_date),
        # get the latest feature value where ts_available <= bar_date.
        result = bars.clone()

        for name in names:
            feat = features.filter(pl.col("feature_name") == name)
            if feat.is_empty():
                continue

            # Pivot to wide: one column per symbol? No — we need per-symbol join.
            # Strategy: for each feature name, do an asof join
            feat_clean = feat.select([
                pl.col("symbol"),
                pl.col("ts_available").alias("_join_ts"),
                pl.col("feature_value").alias(name),
            ]).sort(["_join_ts"])

            # Asof join: for each (symbol, bar_date) in result, find the
            # latest feature row where symbol matches and _join_ts <= bar_date
            joined = result.sort(bar_date_col).join_asof(
                feat_clean.sort("_join_ts"),
                left_on=bar_date_col,
                right_on="_join_ts",
                by="symbol",
                strategy="backward",  # latest value <= bar_date
            )

            # Keep the feature column, drop join artifacts
            if name in joined.columns:
                result = result.with_columns(
                    joined[name].alias(name)
                )
            else:
                result = result.with_columns(
                    pl.lit(None, dtype=pl.Float64).alias(name)
                )

        return result

    def join_summary(self, result: pl.DataFrame, feature_names: list[str]) -> pl.DataFrame:
        """
        Report coverage: what fraction of bar dates have each feature populated.
        """
        total = result.height
        rows = []
        for name in feature_names:
            if name in result.columns:
                populated = result[name].drop_nulls().len()
                rows.append({
                    "feature": name,
                    "populated": populated,
                    "total": total,
                    "coverage_pct": round(populated / total * 100, 1) if total > 0 else 0.0,
                })
        return pl.DataFrame(rows)
