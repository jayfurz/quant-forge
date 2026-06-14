"""
Fama–MacBeth cross-sectional regression.

The single-feature IC answers "does this feature predict returns?". To answer
"does it predict returns *beyond* what momentum/size already explain?" you run a
multivariate cross-sectional regression each period and average the slopes:

    1. each period t: forward_return_i = a_t + Σ_k b_{k,t} · feature_{k,i} + e_i
    2. the Fama–MacBeth estimate of factor k is the time-series mean of b_{k,t},
       and its t-stat is mean(b_k) / (std(b_k) / sqrt(T)).

Features are standardized cross-sectionally within each period, so the slopes
are directly comparable (return per 1σ of the feature) and a feature with a
significant own-IC can still come out insignificant here once correlated
features are controlled for.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import numpy as np
import polars as pl

logger = logging.getLogger(__name__)


def _infer_horizon(forward_col: str) -> Optional[int]:
    m = re.search(r"(\d+)d", forward_col)
    return int(m.group(1)) if m else None


def fama_macbeth(
    data: pl.DataFrame,
    feature_cols: list[str],
    forward_col: str = "forward_20d_return",
    period_col: str = "date",
    rebalance_days: Optional[int] = None,
    min_obs_per_period: Optional[int] = None,
) -> dict:
    """
    Run a Fama–MacBeth regression of ``forward_col`` on ``feature_cols``.

    Uses the same non-overlapping rebalance sampling as the study runner so the
    per-period slopes are (approximately) independent before averaging.

    Returns:
        {
          "features": [...],
          "coefficients": {feat: {"mean": .., "t_stat": .., "std": ..}},
          "n_periods": int,
          "avg_r2": float,
          "rebalance_days": int,
        }
    """
    if rebalance_days is None:
        rebalance_days = _infer_horizon(forward_col) or 1
    rebalance_days = max(1, rebalance_days)
    # need enough names to fit intercept + k slopes with a residual d.o.f.
    min_obs = min_obs_per_period or (len(feature_cols) + 2)

    df = data.drop_nulls(subset=[*feature_cols, forward_col])

    # Non-overlapping rebalance dates.
    if rebalance_days > 1:
        sample = (
            df.select(period_col).unique().sort(period_col)
            .with_row_index("_i")
            .filter(pl.col("_i") % rebalance_days == 0)
            .select(period_col)
        )
        df = df.join(sample, on=period_col, how="inner")

    per_period_coefs: list[np.ndarray] = []
    r2s: list[float] = []

    for (_, sub) in df.group_by(period_col, maintain_order=True):
        if sub.height < min_obs:
            continue
        y = sub[forward_col].to_numpy().astype(float)
        # Standardize each feature within the period (z-score); skip zero-var.
        cols = []
        ok = True
        for f in feature_cols:
            x = sub[f].to_numpy().astype(float)
            sd = x.std()
            if sd == 0 or not np.isfinite(sd):
                ok = False
                break
            cols.append((x - x.mean()) / sd)
        if not ok:
            continue
        X = np.column_stack([np.ones_like(y), *cols])  # intercept + features
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        per_period_coefs.append(beta)
        resid = y - X @ beta
        ss_tot = ((y - y.mean()) ** 2).sum()
        r2s.append(1.0 - (resid @ resid) / ss_tot if ss_tot > 0 else 0.0)

    if not per_period_coefs:
        return {
            "features": feature_cols,
            "coefficients": {f: {"mean": 0.0, "t_stat": 0.0, "std": 0.0} for f in feature_cols},
            "n_periods": 0, "avg_r2": 0.0, "rebalance_days": rebalance_days,
        }

    B = np.vstack(per_period_coefs)  # rows = periods, cols = [intercept, *features]
    n = B.shape[0]
    coefficients = {}
    for k, f in enumerate(feature_cols, start=1):
        series = B[:, k]
        mean = float(series.mean())
        std = float(series.std(ddof=1)) if n > 1 else 0.0
        t = mean / (std / np.sqrt(n)) if std > 0 else 0.0
        coefficients[f] = {"mean": mean, "t_stat": t, "std": std}

    return {
        "features": feature_cols,
        "coefficients": coefficients,
        "n_periods": n,
        "avg_r2": float(np.mean(r2s)) if r2s else 0.0,
        "rebalance_days": rebalance_days,
    }
