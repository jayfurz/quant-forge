"""
Event study — abnormal returns around discrete events.

Where the cross-sectional factor work asks "does a slow-moving feature rank
stocks?", an event study asks "does the stock react to a specific dated event?".
For contract awards this is the more natural frame: a large award is a public,
point-in-time announcement, and any alpha is most likely a reaction/drift around
it rather than a persistent factor tilt.

Method:
  * abnormal return AR_t = r_stock,t − r_benchmark,t   (benchmark = sector ETF,
    so sector-wide moves are removed and we isolate the idiosyncratic reaction)
  * align every event to event day t0 = first trading day on/after the event's
    available date, then collect AR over relative days [−pre, +post]
  * AAR(τ) = mean AR across events at relative day τ; CAAR = cumulative AAR
  * CAR over a window [a,b] per event = Σ AR; report mean CAR and its t-stat
    (mean / (std/√N)) across events.

PIT: the caller is responsible for passing an *available* event date (e.g.
action_date + reporting/announcement lag). Post-event windows [+1, +k] are the
tradeable part; pre-event windows are descriptive only.
"""

from __future__ import annotations

import logging

import numpy as np
import polars as pl

logger = logging.getLogger(__name__)


class EventStudy:
    def __init__(
        self,
        bars: pl.DataFrame,
        events: pl.DataFrame,
        pre: int = 5,
        post: int = 60,
        date_col: str = "date",
        symbol_col: str = "symbol",
        close_col: str = "close",
        benchmark_col: str = "benchmark_close",
        event_date_col: str = "event_date",
    ):
        """
        Args:
            bars: [symbol, date, close, benchmark_close] (daily, all symbols).
            events: [symbol, event_date(, amount, ...)] one row per event.
            pre/post: window in trading days around the event day.
        """
        if benchmark_col not in bars.columns:
            raise ValueError(f"bars must contain '{benchmark_col}' for abnormal returns")
        self.pre, self.post = pre, post
        self.symbol_col, self.date_col = symbol_col, date_col
        self.event_date_col = event_date_col
        self.events = events

        # Per-symbol aligned arrays of abnormal return (stock − benchmark).
        b = bars.sort([symbol_col, date_col]).with_columns([
            (pl.col(close_col) / pl.col(close_col).shift(1).over(symbol_col) - 1.0)
            .alias("_r"),
            (pl.col(benchmark_col) / pl.col(benchmark_col).shift(1) - 1.0)
            .alias("_rb"),
        ]).with_columns(((pl.col("_r") - pl.col("_rb")) * 100.0).alias("_ar"))

        self._by_symbol: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for sym, sub in b.group_by(symbol_col, maintain_order=True):
            sym = sym[0] if isinstance(sym, tuple) else sym
            d = sub[date_col].to_numpy().astype("datetime64[ns]").astype("int64")
            ar = sub["_ar"].to_numpy().astype(float)
            self._by_symbol[sym] = (d, ar)

    def run(self, windows: list[tuple[int, int]] | None = None) -> dict:
        if windows is None:
            windows = [(-self.pre, -1), (0, 0), (1, 5), (1, 20), (1, self.post)]

        rel = np.arange(-self.pre, self.post + 1)
        rows = []  # AR matrix, one row per usable event
        amounts = []
        for ev in self.events.iter_rows(named=True):
            sym = ev[self.symbol_col]
            entry = self._by_symbol.get(sym)
            if entry is None:
                continue
            dates, ar = entry
            ev_int = np.datetime64(ev[self.event_date_col], "ns").astype("int64")
            t0 = int(np.searchsorted(dates, ev_int, side="left"))  # first day >= event
            if t0 >= len(dates):
                continue
            line = np.full(rel.shape, np.nan)
            for k, r in enumerate(rel):
                pos = t0 + r
                if 0 <= pos < len(dates):
                    line[k] = ar[pos]
            rows.append(line)
            amounts.append(ev.get("amount", np.nan))

        if not rows:
            return {"n_events": 0, "windows": {}, "caar": [], "rel_days": rel.tolist()}

        M = np.vstack(rows)              # events × rel_days
        amounts = np.array(amounts, dtype=float)
        aar = np.nanmean(M, axis=0)
        caar = np.nancumsum(aar)         # cumulative average abnormal return

        def car_stats(a: int, b: int, mask: np.ndarray | None = None) -> dict:
            i0, i1 = a + self.pre, b + self.pre
            sub = M[:, i0:i1 + 1]
            if mask is not None:
                sub = sub[mask]
            complete = ~np.isnan(sub).any(axis=1)
            car = sub[complete].sum(axis=1)
            n = car.size
            mean = float(car.mean()) if n else 0.0
            std = float(car.std(ddof=1)) if n > 1 else 0.0
            t = mean / (std / np.sqrt(n)) if (n > 1 and std > 0) else 0.0
            hit = float((car > 0).mean() * 100) if n else 0.0
            return {"window": f"[{a},{b}]", "n": int(n), "mean_car_pct": mean,
                    "t_stat": t, "hit_rate_pct": hit}

        window_stats = {f"[{a},{b}]": car_stats(a, b) for a, b in windows}

        # Size split: do bigger awards drift more? Terciles by amount.
        size_stats = {}
        if np.isfinite(amounts).sum() >= 6:
            finite = np.isfinite(amounts)
            q1, q2 = np.nanquantile(amounts[finite], [1/3, 2/3])
            buckets = {
                "small": amounts <= q1,
                "mid": (amounts > q1) & (amounts <= q2),
                "large": amounts > q2,
            }
            drift = (1, min(20, self.post))
            for label, mask in buckets.items():
                size_stats[label] = car_stats(*drift, mask=mask & np.isfinite(amounts))

        return {
            "n_events": int(M.shape[0]),
            "rel_days": rel.tolist(),
            "caar": caar.tolist(),
            "aar": aar.tolist(),
            "windows": window_stats,
            "size_buckets": size_stats,
        }
