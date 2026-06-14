# Research Notes — Contract Award Velocity (v2: rearchitected)

**Date:** 2026-06-14
**Branch:** `claude/research-h46cfx`

This is the second pass. v1 (below, "Appendix") got the flagship study *running*
and exposed that even once it ran, both the signal and the harness were not to
be trusted. v2 **fixes the bugs and rearchitects** the research stack and the
C++ engine so the conclusion is actually believable.

---

## TL;DR

- **Data, rebuilt point-in-time.** The feature is now built from
  **transaction-level** USAspending obligations (per-obligation `action_date` +
  amount, paginated) instead of award-level *current cumulative* totals stamped
  at a single PoP-start date. 37k transactions → **5,542 feature points across
  23 names** (v1: 100 points / 13 names), with a reporting-lag-adjusted
  `ts_available`.
- **Lookahead removed.** Velocity normalisation is now a **trailing/expanding
  z-score** (was full-sample) and the rolling windows are **calendar-based**
  (`90d` / `730d`) instead of row-count based.
- **Statistics, made honest.** The study runner samples **non-overlapping**
  rebalance dates, annualises by the rebalance frequency (not √252), reports an
  **IC t-stat**, balances quantile buckets per period, and skips periods too
  thin to sort. Sharpe figures dropped from a fantasy 5–10 to a sane 0.2–1.3.
- **Verdict (unchanged, now credible): the contract-velocity feature has no
  statistically significant edge.** Its IC t-stats are 1.1 / 0.7 / 0.0 across
  20/60/120d — all below the |t|≈2 bar. A plain 63-day price-momentum baseline
  is the only thing that clears it (120d IC 0.28, **t = 3.15**).
- **C++ engine: builds and is correct enough to trust its metrics.** The build
  no longer requires unused libraries; the metrics layer (daily returns,
  Sortino, win rate, profit factor, trade P&L) was rewritten from real
  round-trip accounting; and the strategy no longer cross-contaminates signals
  across symbols.

---

## Part 1 — Bugs fixed

### Breaking (the study could not run / produce output)
1. **Yahoo downloader** used a bot User-Agent → HTTP 429 on every request.
   Now uses a browser UA with exponential-backoff retry.
2. **Downloader↔study column mismatch** — study looked for `"Award Amount"`,
   downloader emitted `amount`. (Superseded in v2 by the transaction path.)
3. **`KeyError` in the drawdown calc** — read `cumulative_spread` from the
   wrong frame.

### Correctness (ran, but wrong numbers)
4. **Inverted quintile sign** — ranked descending so Q1 was the *top* bucket,
   making the reported "Q5−Q1" spread the negative of the truth. Now ranks
   ascending; spread sign agrees with IC.
5. **Drawdown ÷ near-zero peak** produced values like −571,992%. Now additive
   peak-to-trough in cumulative-spread points.
6. **PIT join dropped pre-window features** — `query_range` lower-bounded by the
   first bar date, so a feature available *before* the first bar (still the
   valid carry-forward value) was clipped out, leaving early bars null. Now
   queries all history up to the last bar. *(Caught by a regression test.)*
7. **IC NaN poisoning** — `pl.corr` returns NaN (not null) for thin periods;
   `drop_nulls` missed it, so mean IC came out NaN. Now filters NaN and handles
   empty IC frames.
8. **Cleaner dropped Fridays** — `dt.weekday() < 5` (polars weekday is 1–7).
   Now `<= 5`. Also `align_to_trading_calendar` join crashed on Datetime vs
   Date keys; dtype is now matched.
9. **Cleaner outliers** flagged on raw price *level* (meaningless for a trend);
   now on daily returns.
10. **`signal_builder`** `'expected' in dir()` hack and a duplicate
    `RISK_SEVERITY` key; **`pipeline.py`** imported `polars` only under
    `__main__` so `run_pipeline()` broke on import.

### C++ (see Part 3)
Build deps, daily-returns off-by-one, Sortino denominator, win-rate/profit-factor
nonsense, realized-P&L sign on closes, buying-power double-count, RSI flat-series,
and the strategy cross-symbol contamination.

---

## Part 2 — Research-stack rearchitecture

| Concern | Before | After |
|--------|--------|-------|
| Contract data | award-level, top-100-by-$, cumulative total @ PoP start | **transaction-level**, paginated, per-obligation `action_date` |
| Availability | `ts_available` = PoP start (1984–2028!) | `action_date + reporting_lag` (default 30d) |
| Normalisation | full-sample per-symbol z-score (lookahead) | **trailing/expanding** z-score (`research.features.trailing_zscore`) |
| Rolling windows | row-count (`window_size=90` rows) | **calendar** (`rolling_sum_by("action_date","90d")`) |
| Periods | every bar (overlapping → inflated stats) | **non-overlapping** rebalance sampling |
| Annualisation | √252 always | √(252 / rebalance_days) |
| Significance | IC-IR only | IC **t-stat** + n_periods |
| Quantiles | global rank → unequal buckets | per-period balanced buckets + thin-period guard |

New module `python/research/features.py` (`build_award_velocity`,
`trailing_zscore`) holds the PIT feature logic so it is unit-testable in
isolation. The study (`studies/contract_award_velocity.py`) is now a thin driver
over it.

### Results (live data, 2026-06-14)

| feature | horizon | IC | IC t-stat | Q5−Q1 | Sharpe (ann.) |
|---------|--------:|---:|----------:|------:|--------------:|
| contract_award_velocity_z | 20d  | 0.071 | 1.09 | +2.02% | 1.06 |
| | 60d  | 0.147 | 0.72 | +4.63% | 0.77 |
| | 120d | 0.000 | 0.00 | +1.76% | 0.25 |
| price_momentum_63d (baseline) | 20d  | 0.003 | 0.05 | +2.05% | 0.80 |
| | 60d  | 0.092 | 0.93 | +6.04% | 0.66 |
| | 120d | **0.283** | **3.15** | **+18.41%** | 1.28 |

**Interpretation.** None of the contract-velocity t-stats reach significance.
The richer transaction-level feature is real and PIT-clean, but on this 3-year,
~23-name defense universe sampled non-overlapping there simply aren't enough
independent observations to distinguish its IC from zero — and what edge momentum
shows (120d, t=3.15) the contract feature does not add to. Honest answer: **not a
tradable standalone signal on this sample.**

### Remaining limitations (now the *honest* ones, not bugs)
- **Low statistical power.** Non-overlapping sampling on 3 years leaves 5–12
  periods per horizon. The right next step is a longer history and/or a wider
  universe, not more parameter tweaking.
- **Reporting lag is a flat 30d assumption**; true FPDS lag varies.
- **Multiple testing** across horizons/features is uncorrected — treat any single
  cell as exploratory.

---

## Part 3 — C++ engine rearchitecture

The engine compiled but its build was blocked and its outputs were wrong.

- **Build:** `fmt` / `nlohmann_json` / `SQLite3` were `find_package(... REQUIRED)`
  yet unused by any source (and `FindSQLite3` here exposes no usable target).
  Removed; the engine now configures and builds with **zero external deps**.
- **Metrics (`metrics.cpp`), rewritten from real accounting:**
  - `daily_returns` was off-by-one and dropped the last day → corrupted
    Sharpe/Sortino/vol. Now one clean close-to-close return per day.
  - Sortino downside deviation divided by the *loser* count; now by total N.
  - `win_rate` was ~always 0 and `profit_factor` hard-returned 999 (it treated a
    sell *price* as profit). Both now derive from `realized_trade_pnls`, a FIFO
    average-cost round-trip P&L. `winning/losing/total_trades` and
    `avg_trade_pnl` likewise.
- **Portfolio (`engine.cpp`):** realized P&L had the wrong sign on a full close
  (profitable long exits booked as losses) and over-counted on flips; rewritten
  with proper average-cost close/partial/flip handling. `buying_power` no longer
  double-counts cash.
- **Indicators:** RSI on a flat series returned 100 (dead both-zero branch); now
  the neutral 50.
- **Strategy (the big one):** `StrategyFunc` didn't receive the symbol, so the
  momentum strategy updated *every* symbol's state on each bar and emitted
  signals for instruments it never saw. `StrategyFunc` now takes `symbol`; the
  strategy keeps clean per-symbol state. Buy-and-hold likewise sizes each name
  off its own first bar.
- **Tests tightened** (loose `>= 0` checks replaced with exact assertions):
  36 cases / 82 assertions pass, including new round-trip-P&L, partial-close,
  and flip tests. `qf-runner` on the sample data now reports real win rate /
  profit factor / trade counts.

---

## Reproduce

```bash
# Python study (live data)
python studies/contract_award_velocity.py --years 3 \
    --out reports/contract_award_velocity --horizons 20,60,120
python -m pytest python/tests -q

# C++ engine
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j
./build/qf-tests
./build/qf-runner --bars data/sample_bars.csv --strategy momentum_ema_hysteresis
```

---

---

# Appendix — v1 notes (original audit)

The first pass established that the flagship study had **never run** (three
breaking bugs), then once forced to run produced **IC ≈ 0** for the contract
feature alongside an inverted-sign spread and a −571,992% drawdown in the
harness. Those findings motivated the v2 rearchitecture above; the specific v1
bugs are folded into Part 1. The headline has survived the rebuild: the contract
feature still shows no edge, but now that statement rests on PIT-clean data and
honest, non-overlapping statistics rather than on broken plumbing.
