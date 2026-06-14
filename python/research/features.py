"""
PIT-safe feature engineering primitives.

Everything here is built so that a value computed for time ``t`` uses *only*
information available at or before ``t``. This is the opposite of the original
inline feature code in the study, which:

  * z-scored against the **full-sample** per-symbol mean/std (lookahead), and
  * used **row-based** rolling windows (``window_size=90`` = 90 award rows, not
    90 days) on a sparse series where 90 rows could span years.

See reports/contract_award_velocity/RESEARCH_NOTES.md, caveats A and B.
"""

from __future__ import annotations

import logging
from datetime import datetime

import polars as pl

logger = logging.getLogger(__name__)


def trailing_zscore(
    df: pl.DataFrame,
    value_col: str,
    by: str = "symbol",
    time_col: str = "ts_available",
    min_periods: int = 8,
    out_col: str | None = None,
) -> pl.DataFrame:
    """
    Expanding (trailing) z-score within each ``by`` group.

    For each row the mean and sample std are computed over that group's history
    **up to and including the current row** — never the whole sample. Rows with
    fewer than ``min_periods`` prior observations (or zero std) get a null
    z-score, which downstream code drops.

    Implemented with cumulative sums so it stays vectorised:
        mean_t = S1_t / n_t
        var_t  = (S2_t - n_t * mean_t^2) / (n_t - 1)
    """
    out_col = out_col or f"{value_col}_z"
    df = df.sort([by, time_col])

    n = pl.int_range(1, pl.len() + 1).over(by)
    s1 = pl.col(value_col).cum_sum().over(by)
    s2 = (pl.col(value_col) ** 2).cum_sum().over(by)

    mean = s1 / n
    # sample variance; guard n == 1
    var = pl.when(n > 1).then((s2 - n * mean**2) / (n - 1)).otherwise(None)
    std = var.sqrt()

    z = pl.when((n >= min_periods) & std.is_not_null() & (std > 0)) \
          .then((pl.col(value_col) - mean) / std) \
          .otherwise(None)

    return df.with_columns(z.alias(out_col))


def build_award_velocity(
    transactions: pl.DataFrame,
    recent_days: int = 90,
    baseline_days: int = 730,
    reporting_lag_days: int = 30,
    zscore_min_periods: int = 8,
    as_of: datetime | None = None,
    feature_name: str = "contract_award_velocity_z",
) -> pl.DataFrame:
    """
    Build a point-in-time contract-award-velocity feature from transaction-level
    obligations.

    Args:
        transactions: DataFrame with at least [symbol, action_date, amount].
            ``action_date`` may be a string (YYYY-MM-DD) or a date.
        recent_days:   short window whose obligation total is the "recent" pace.
        baseline_days: long window used to compute the average ``recent_days``
                       pace, i.e. the normaliser.
        reporting_lag_days: federal obligations are not public the instant they
            are booked. ``ts_available = action_date + reporting_lag_days`` so
            the feature can only be traded after it would actually be knowable.
        zscore_min_periods: minimum history before a z-score is emitted.
        as_of: drop any action_date after this (defends against future-dated
            rows); defaults to "now".

    Returns the FeatureStore schema:
        symbol, ts_available, feature_name, feature_value, source,
        source_event_id, asof_date
    """
    if transactions.is_empty():
        return pl.DataFrame()

    as_of = as_of or datetime.now()

    df = transactions
    # Normalise action_date → Date, drop unparseable/future rows.
    if df.schema.get("action_date") == pl.Utf8:
        df = df.with_columns(
            pl.col("action_date").str.slice(0, 10).str.strptime(pl.Date, strict=False)
        )
    else:
        df = df.with_columns(pl.col("action_date").cast(pl.Date, strict=False))

    df = df.drop_nulls(subset=["symbol", "action_date", "amount"]).filter(
        (pl.col("action_date") <= as_of.date()) & (pl.col("amount") > 0)
    )
    if df.is_empty():
        logger.warning("No valid transactions after date/amount filtering")
        return pl.DataFrame()

    # Net daily obligations per symbol (a transaction date can repeat).
    daily = (
        df.group_by(["symbol", "action_date"])
        .agg(pl.col("amount").sum().alias("daily_amount"))
        .sort(["symbol", "action_date"])
    )

    # TIME-based rolling windows (not row counts) — this is the key fix.
    daily = daily.with_columns(
        pl.col("daily_amount")
        .rolling_sum_by("action_date", window_size=f"{recent_days}d")
        .over("symbol")
        .alias("recent_sum"),
        pl.col("daily_amount")
        .rolling_sum_by("action_date", window_size=f"{baseline_days}d")
        .over("symbol")
        .alias("baseline_sum"),
    )

    # Expected recent-window pace from the long baseline, then velocity ratio.
    scale = recent_days / baseline_days
    daily = daily.with_columns(
        (pl.col("baseline_sum") * scale).alias("expected_recent")
    ).with_columns(
        pl.when(pl.col("expected_recent") > 0)
        .then(pl.col("recent_sum") / pl.col("expected_recent"))
        .otherwise(None)
        .alias("velocity_raw")
    )

    daily = daily.drop_nulls(subset=["velocity_raw"])
    if daily.is_empty():
        logger.warning("No velocity values after baseline normalisation")
        return pl.DataFrame()

    # Trailing (PIT) z-score per symbol — NOT full-sample.
    daily = trailing_zscore(
        daily, "velocity_raw", by="symbol", time_col="action_date",
        min_periods=zscore_min_periods, out_col="velocity_z",
    ).drop_nulls(subset=["velocity_z"])

    if daily.is_empty():
        logger.warning("No velocity z-scores after min_periods=%d filter",
                       zscore_min_periods)
        return pl.DataFrame()

    lag = pl.duration(days=reporting_lag_days)
    return daily.select([
        pl.col("symbol"),
        (pl.col("action_date") + lag).cast(pl.Datetime("us")).alias("ts_available"),
        pl.lit(feature_name).alias("feature_name"),
        pl.col("velocity_z").alias("feature_value"),
        pl.lit("usaspending_tx").alias("source"),
        pl.lit("").alias("source_event_id"),
        pl.col("action_date").cast(pl.Datetime("us")).alias("asof_date"),
    ])
