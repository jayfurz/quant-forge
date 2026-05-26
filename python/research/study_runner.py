"""
SignalStudyRunner — rank assets by feature, compute quintile returns, IC stats.

Core research tool. Given joined data (bars + features + forward returns),
ranks symbols by feature value each period, buckets into quintiles,
and computes forward performance per bucket.

Answers the question:
    "Does this feature predict anything tradable, out of sample,
     after costs, beyond a simple baseline?"
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import polars as pl

logger = logging.getLogger(__name__)


class SignalStudyRunner:
    """
    Runs a signal study: rank → quintile → forward returns → stats.

    Usage:
        runner = SignalStudyRunner(joined_df)
        report = runner.run(
            feature_name="contract_award_velocity_z",
            forward_col="forward_20d_return",
        )
        runner.save_report(report, "reports/my_study/")
    """

    def __init__(self, data: pl.DataFrame):
        """
        Args:
            data: Joined DataFrame from PointInTimeJoiner + ForwardReturnLabeler.
                  Must contain: symbol, date, feature columns, forward_*d_return columns.
        """
        self.data = data
        self._validate_columns()

    def _validate_columns(self):
        required = ["symbol", "date"]
        missing = [c for c in required if c not in self.data.columns]
        if missing:
            raise ValueError(f"Study data missing required columns: {missing}")

    def run(
        self,
        feature_name: str,
        forward_col: str = "forward_20d_return",
        period_col: str = "date",
        n_quantiles: int = 5,
        benchmark_col: Optional[str] = None,
    ) -> dict:
        """
        Run a full signal study.

        Returns a dict with all results: quintile returns, IC stats,
        long/short equity curves, and summary metrics.
        """
        if feature_name not in self.data.columns:
            raise ValueError(
                f"Feature '{feature_name}' not in data. Available: "
                f"{[c for c in self.data.columns if not c.startswith('forward_')]}"
            )
        if forward_col not in self.data.columns:
            raise ValueError(
                f"Forward column '{forward_col}' not in data. Available: "
                f"{[c for c in self.data.columns if c.startswith('forward_')]}"
            )

        logger.info("Running study: %s → %s (%d quantiles)",
                     feature_name, forward_col, n_quantiles)

        # ── 1. Compute quantile ranks per period ───────────────────
        df = self.data.clone()

        # Drop rows where feature or forward return is null
        df = df.drop_nulls(subset=[feature_name, forward_col])

        # Compute quantile bucket per period
        df = df.with_columns(
            pl.col(feature_name)
            .rank("ordinal", descending=True)  # highest value = rank 1
            .over(period_col)
            .alias("_rank")
        )

        # Compute quantile boundaries
        max_rank = df["_rank"].max()
        if max_rank is None or max_rank == 0:
            raise ValueError("No ranked data after filtering nulls")

        df = df.with_columns(
            ((pl.col("_rank") - 1) * n_quantiles // max_rank + 1)
            .cast(pl.Int32)
            .alias("quantile")
        )

        # Clamp to [1, n_quantiles]
        df = df.with_columns(
            pl.col("quantile").clip(1, n_quantiles).alias("quantile")
        )

        # ── 2. Quintile forward returns ────────────────────────────
        quintile_returns = df.group_by(["quantile", period_col]).agg([
            pl.col(forward_col).mean().alias("mean_return"),
            pl.col(forward_col).std().alias("std_return"),
            pl.col(forward_col).median().alias("median_return"),
            pl.col("symbol").count().alias("n_stocks"),
            (pl.col(forward_col) > 0).sum().alias("winners"),
        ]).sort([period_col, "quantile"])

        # Per-quintile summary
        quintile_summary = df.group_by("quantile").agg([
            pl.col(forward_col).mean().alias("avg_return"),
            pl.col(forward_col).std().alias("std_return"),
            (pl.col(forward_col) > 0).sum().alias("win_count"),
            pl.col(forward_col).count().alias("total_count"),
        ]).with_columns(
            (pl.col("win_count") / pl.col("total_count") * 100).alias("hit_rate_pct")
        ).sort("quantile")

        # ── 3. Top-minus-bottom spread ─────────────────────────────
        top = quintile_returns.filter(pl.col("quantile") == n_quantiles)
        bottom = quintile_returns.filter(pl.col("quantile") == 1)

        if not top.is_empty() and not bottom.is_empty():
            spread = top.select(period_col).join(
                bottom.select([
                    period_col,
                    pl.col("mean_return").alias("bottom_mean"),
                ]),
                on=period_col,
            ).join(
                top.select([
                    period_col,
                    pl.col("mean_return").alias("top_mean"),
                ]),
                on=period_col,
            ).with_columns(
                (pl.col("top_mean") - pl.col("bottom_mean")).alias("spread")
            ).sort(period_col)
        else:
            spread = pl.DataFrame()

        # ── 4. Information Coefficient (IC) ────────────────────────
        ic_data = df.group_by(period_col).agg([
            pl.corr(feature_name, forward_col).alias("pearson_ic"),
            pl.corr(feature_name, forward_col, method="spearman").alias("spearman_ic"),
        ]).sort(period_col).drop_nulls(subset=["pearson_ic"])

        ic_summary = {
            "pearson_ic_mean": ic_data["pearson_ic"].mean(),
            "pearson_ic_std": ic_data["pearson_ic"].std(),
            "pearson_ic_ir": (
                ic_data["pearson_ic"].mean() / ic_data["pearson_ic"].std()
                if ic_data["pearson_ic"].std() and ic_data["pearson_ic"].std() > 0
                else 0.0
            ),
            "spearman_ic_mean": ic_data["spearman_ic"].mean(),
            "ic_positive_pct": (
                (ic_data["pearson_ic"] > 0).sum() / ic_data.height * 100
                if ic_data.height > 0 else 0.0
            ),
        }

        # ── 5. Long/short equity curve (top quintile long) ─────────
        long_short = None
        if not spread.is_empty():
            long_short = spread.with_columns(
                pl.col("spread").cum_sum().alias("cumulative_spread")
            )

            # Sharpe of the spread
            spread_mean = spread["spread"].mean()
            spread_std = spread["spread"].std()
            sharpe = (spread_mean / spread_std * (252 ** 0.5)
                      if spread_std and spread_std > 0 else 0.0)

            # Max drawdown of spread
            cum = spread["cumulative_spread"]
            peak = cum.cum_max()
            dd = (cum - peak) / peak.abs() * 100
            max_dd = dd.min()
        else:
            sharpe = 0.0
            max_dd = 0.0

        # ── 6. Stability checks ────────────────────────────────────
        # Returns by year
        if "year" not in df.columns:
            df = df.with_columns(
                pl.col(period_col).dt.year().alias("year")
            )

        top_by_year = df.filter(pl.col("quantile") == n_quantiles).group_by("year").agg(
            pl.col(forward_col).mean().alias("top_quintile_return")
        ).sort("year")

        # ── Assemble report ────────────────────────────────────────
        report = {
            "meta": {
                "feature": feature_name,
                "forward_col": forward_col,
                "n_quantiles": n_quantiles,
                "n_periods": df[period_col].n_unique(),
                "n_symbols": df["symbol"].n_unique(),
                "n_observations": df.height,
                "date_range": [
                    str(df[period_col].min()),
                    str(df[period_col].max()),
                ],
                "generated_at": datetime.now().isoformat(),
            },
            "quintile_summary": quintile_summary.to_dicts(),
            "quintile_spread": {
                "mean_spread": spread["spread"].mean() if not spread.is_empty() else 0.0,
                "std_spread": spread["spread"].std() if not spread.is_empty() else 0.0,
                "sharpe": sharpe,
                "max_drawdown_pct": max_dd,
            },
            "ic_summary": ic_summary,
            "top_quintile_by_year": top_by_year.to_dicts(),
            "quintile_returns": quintile_returns.to_dicts(),
            "ic_by_period": ic_data.to_dicts(),
            "long_short_equity": (
                long_short.select([period_col, "spread", "cumulative_spread"]).to_dicts()
                if long_short is not None else []
            ),
            "data": {
                "full": df,
                "quintile_returns_df": quintile_returns,
                "ic_df": ic_data,
                "spread_df": spread,
                "long_short_df": long_short,
            },
        }

        return report

    @staticmethod
    def save_report(report: dict, output_dir: str | Path) -> None:
        """Save all report artifacts to disk."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        # CSV exports
        data = report["data"]
        if "quintile_returns_df" in data and not data["quintile_returns_df"].is_empty():
            data["quintile_returns_df"].write_csv(out / "quintile_returns.csv")
        if "ic_df" in data and not data["ic_df"].is_empty():
            data["ic_df"].write_csv(out / "ic_by_month.csv")
        if "long_short_df" in data and data["long_short_df"] is not None:
            if not data["long_short_df"].is_empty():
                data["long_short_df"].select(
                    ["date", "spread", "cumulative_spread"]
                ).write_csv(out / "long_short_equity.csv")
        if "full" in data:
            # Write feature coverage info (not the full dataset — too large)
            pass

        # JSON report (without the heavy DataFrames)
        json_report = {k: v for k, v in report.items() if k != "data"}
        (out / "metrics.json").write_text(
            json.dumps(json_report, indent=2, default=str)
        )

        # Summary markdown
        meta = report["meta"]
        qs = report["quintile_summary"]
        ic = report["ic_summary"]
        spread = report["quintile_spread"]

        lines = [
            f"# Signal Study: {meta['feature']}",
            "",
            f"**Target:** {meta['forward_col']}",
            f"**Periods:** {meta['n_periods']}  |  **Symbols:** {meta['n_symbols']}  |  **Obs:** {meta['n_observations']}",
            f"**Date Range:** {meta['date_range'][0]} → {meta['date_range'][1]}",
            "",
            "## Quintile Returns",
            "",
            "| Q | Avg Return | Std | Hit Rate | N |",
            "|---|-----------|-----|----------|---|",
        ]
        for q in qs:
            lines.append(
                f"| Q{q['quantile']} | {q['avg_return']:.3f}% | {q['std_return']:.3f}% | "
                f"{q['hit_rate_pct']:.1f}% | {q['total_count']} |"
            )

        lines += [
            "",
            "## Spread (Q{n_quantiles} - Q1)".format(n_quantiles=meta["n_quantiles"]),
            "",
            f"- Mean spread: {spread['mean_spread']:.3f}%",
            f"- Sharpe: {spread['sharpe']:.2f}",
            f"- Max drawdown: {spread['max_drawdown_pct']:.1f}%",
            "",
            "## Information Coefficient",
            "",
            f"- Pearson IC mean: {ic['pearson_ic_mean']:.4f}",
            f"- IC std: {ic['pearson_ic_std']:.4f}",
            f"- IC IR: {ic['pearson_ic_ir']:.3f}",
            f"- IC positive: {ic['ic_positive_pct']:.1f}%",
        ]

        (out / "summary.md").write_text("\n".join(lines) + "\n")

        logger.info("Report saved to %s/ (%d files)", out,
                     len(list(out.iterdir())))
