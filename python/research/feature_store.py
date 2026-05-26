"""
FeatureStore — Parquet-backed point-in-time feature storage.

Every feature row MUST have a `ts_available` field — the timestamp
at which the feature value becomes known to the system. This is NOT
the event date, quarter end, or filing date. It is the first moment
the strategy could legally trade on the information.

Schema:
    symbol             str      — ticker
    ts_available       datetime — when the feature became knowable
    feature_name       str      — unique feature identifier
    feature_value      float    — numeric value (z-score recommended)
    source             str      — data source (e.g. "usaspending", "sec_edgar")
    source_event_id    str      — ID of the source event (award ID, filing accession)
    asof_date          datetime — the date the event actually occurred (for debugging)
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import polars as pl

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = [
    "symbol", "ts_available", "feature_name",
    "feature_value", "source", "source_event_id", "asof_date"
]


class FeatureStore:
    """Parquet-backed store with strict PIT query semantics."""

    def __init__(self, base_dir: str | Path = "data/features"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, pl.DataFrame] = {}

    # ── Write ──────────────────────────────────────────────────────

    def add_features(self, df: pl.DataFrame) -> int:
        """
        Insert features. Validates schema, partitions by feature_name,
        appends to Parquet files.

        Returns number of rows inserted.
        """
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        if df.is_empty():
            return 0

        # Cast types
        df = df.with_columns([
            pl.col("symbol").cast(pl.Utf8),
            pl.col("ts_available").cast(pl.Datetime("us")),
            pl.col("feature_name").cast(pl.Utf8),
            pl.col("feature_value").cast(pl.Float64),
            pl.col("source").cast(pl.Utf8),
            pl.col("source_event_id").cast(pl.Utf8),
            pl.col("asof_date").cast(pl.Datetime("us")),
        ])

        # Drop explicit nulls
        df = df.drop_nulls(subset=["symbol", "ts_available", "feature_name", "feature_value"])

        count = 0
        for feature_name in df["feature_name"].unique().to_list():
            subset = df.filter(pl.col("feature_name") == feature_name)
            feature_dir = self.base_dir / feature_name
            feature_dir.mkdir(parents=True, exist_ok=True)
            path = feature_dir / "data.parquet"

            if path.exists():
                existing = pl.read_parquet(path)
                combined = pl.concat([existing, subset], how="diagonal_relaxed")
                # Deduplicate by (symbol, ts_available, feature_name)
                combined = combined.unique(
                    subset=["symbol", "ts_available", "feature_name"],
                    keep="last"
                )
                combined = combined.sort("ts_available")
                combined.write_parquet(path)
            else:
                subset = subset.sort("ts_available")
                subset.write_parquet(path)

            count += subset.height
            # Invalidate cache for this feature
            self._cache.pop(feature_name, None)

        logger.info("Inserted %d feature rows across %d features",
                     count, df["feature_name"].n_unique())
        return count

    # ── Query ───────────────────────────────────────────────────────

    def query(
        self,
        symbol: str,
        ts: datetime,
        feature_names: Optional[list[str]] = None,
    ) -> pl.DataFrame:
        """
        Return all features available for `symbol` at or before `ts`.

        This is the PIT-safe query — no lookahead.
        """
        names = feature_names or self.feature_names()
        frames = []

        for name in names:
            df = self._load_feature(name)
            if df is None:
                continue
            match = df.filter(
                (pl.col("symbol") == symbol) &
                (pl.col("ts_available") <= ts)
            )
            if not match.is_empty():
                frames.append(match.sort("ts_available").tail(1))

        if not frames:
            return pl.DataFrame(schema={
                "symbol": pl.Utf8, "ts_available": pl.Datetime("us"),
                "feature_name": pl.Utf8, "feature_value": pl.Float64,
                "source": pl.Utf8, "source_event_id": pl.Utf8,
                "asof_date": pl.Datetime("us"),
            })

        return pl.concat(frames, how="diagonal_relaxed")

    def query_range(
        self,
        symbols: list[str],
        features: list[str],
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame:
        """
        Get all feature values for date range. Used by study runner.

        Returns one row per (symbol, ts_available, feature_name) with
        the value available at each point in time.
        """
        frames = []
        for name in features:
            df = self._load_feature(name)
            if df is None:
                continue
            match = df.filter(
                pl.col("symbol").is_in(symbols) &
                (pl.col("ts_available") >= start) &
                (pl.col("ts_available") <= end)
            )
            if not match.is_empty():
                frames.append(match)

        if not frames:
            return pl.DataFrame(schema={
                "symbol": pl.Utf8, "ts_available": pl.Datetime("us"),
                "feature_name": pl.Utf8, "feature_value": pl.Float64,
                "source": pl.Utf8, "source_event_id": pl.Utf8,
                "asof_date": pl.Datetime("us"),
            })

        return pl.concat(frames, how="diagonal_relaxed").sort(["symbol", "ts_available"])

    def feature_names(self) -> list[str]:
        """List all known feature names."""
        names = []
        for d in self.base_dir.iterdir():
            if d.is_dir() and (d / "data.parquet").exists():
                names.append(d.name)
        return sorted(names)

    def feature_summary(self) -> pl.DataFrame:
        """Return summary: feature name, row count, date range, symbols."""
        rows = []
        for name in self.feature_names():
            df = self._load_feature(name)
            if df is None:
                continue
            rows.append({
                "feature_name": name,
                "rows": df.height,
                "symbols": df["symbol"].n_unique(),
                "min_ts": df["ts_available"].min(),
                "max_ts": df["ts_available"].max(),
            })
        if not rows:
            return pl.DataFrame()
        return pl.DataFrame(rows)

    # ── Internal ────────────────────────────────────────────────────

    def _load_feature(self, name: str) -> Optional[pl.DataFrame]:
        """Load a feature's Parquet file, with caching."""
        if name in self._cache:
            return self._cache[name]

        path = self.base_dir / name / "data.parquet"
        if not path.exists():
            return None

        df = pl.read_parquet(path)
        self._cache[name] = df
        return df
