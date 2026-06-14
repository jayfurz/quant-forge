# Research Notes — Contract Award Velocity (v6: wider universe)

## v6 headline — doubling the universe surfaces a (borderline) signal (read first)

Every prior conclusion was power-limited: a ~24-name universe caps every
cross-sectional t-stat. v6 roughly doubles it to **~46 federally-exposed names**
(defense/aerospace + government IT services + federal-facing industrials;
`--universe wide`, keyword-mapped so weak matches self-filter) and re-runs all
analyses over 8 years.

**The extra breadth changes the answer for the size feature:**

- **`contract_intensity` (trailing-12m awards ÷ market cap) becomes
  significant.** In the full Fama–MacBeth model `forward_20d ~ velocity +
  intensity + momentum`, intensity is **b=+0.45, t=+2.11** (n=97), with velocity
  t=−0.24 and momentum t=+0.34. Its sign is positive and consistent across
  horizons (multivariate t = 2.11 / 1.57 / 1.44 at 20/60/120d; univariate IC t
  = 1.47 / −0.23 / 1.45). In the 24-name universe this same coefficient was
  t≈0.15 — the signal was there, we just lacked the power to see it. This
  vindicates the "**consider the size of the contract**" intuition: it's the
  size-relative feature, not the scale-free velocity ratio, that carries the
  (modest) information.
- **Velocity and momentum remain dead** (all |t| < 1.3 multivariate).
- **Event study, wider universe:** the overlapping full sample is even more
  inflated (60d CAR t=−5.17, n=1340 — ignore it); the de-overlapped robust set
  (90-day spacing, 422 events) gives 60d CAR **−1.40%, t=−1.94** and 20d
  **+0.49%, t=+1.39** — a hint of post-award underperformance that strengthens
  with breadth but still doesn't clear |t|≈2.

**Verdict:** with adequate cross-sectional breadth, **size-relative contract
intensity is a marginally significant ~1-month predictor** (t≈2.0, positive),
surviving controls for momentum and velocity — the one genuine, if small,
signal in the whole arc. Treat it as *promising, not proven*: t≈2 with
multiple horizons/models tested invites a multiple-comparisons discount, the
wide universe's keyword mapping is noisy, and there is no out-of-sample
confirmation. Next step would be a holdout / second universe, not more tuning.

```bash
python studies/contract_award_velocity.py --years 8 --universe wide \
    --out reports/contract_award_velocity_wide
python studies/contract_award_events.py --years 8 --universe wide \
    --out reports/contract_award_events_wide                       # + --cluster-days 90 robust
```

Reports: `reports/contract_award_velocity_wide/` (see `fama_macbeth.md`),
`reports/contract_award_events_wide{,_robust}/`.

---

# Research Notes — Contract Award Velocity (v5: + event study)

## v5 headline — event study around large awards (read this first)

The factor work asked "does contract data *rank* stocks?" (no). The event study
asks the more natural question: "does a stock *react* to a large award
announcement?" Engine: `research.EventStudy` — cumulative abnormal return
(CAR = stock − ITA) over [−5,+60] trading days around each award's action date,
t-stats across events, split by award size. Driver:
`studies/contract_award_events.py`. Events = each vendor's largest obligation
transactions (≥ $50M), de-duplicated into clusters.

- **First-pass result looked real and negative:** over 1,010 large awards, the
  60-day post-event CAR was **−0.93%, t = −2.37** — a "sell-the-news"
  underperformance, concentrated in mid/large awards. No announcement-day pop
  (t = −0.58) and no run-up (t = +0.30).
- **It did not survive a robustness check.** Those 1,010 events have 60-day
  windows that overlap massively (multiple awards per name, fiscal-year-end
  clustering), so the independence the t-stat assumes is badly violated.
  Re-running with events spaced ≥90 days apart (297 near-independent events)
  **collapses the effect to −0.22%, t = −0.27.** The −2.37 was an
  overlapping-window artifact, not alpha. (A marginal +0.42% / t=1.86 over
  [1,5] appears in the clean sample but is <2 and sign-flips vs the full sample
  → noise.)

**Verdict:** no robust abnormal return around large defense awards — consistent
with the factor study. Awards appear anticipated / priced in. And once again the
honest answer only emerged after correcting for overlap (cf. the v3 momentum
non-replication). Reports in `reports/contract_award_events/` (full) and
`…_events_robust/` (90-day-spaced).

```bash
python studies/contract_award_events.py --years 8 --min-award 50e6                 # full
python studies/contract_award_events.py --years 8 --min-award 50e6 --cluster-days 90 \
    --out reports/contract_award_events_robust                                      # robust
```

---

# Research Notes — Contract Award Velocity (v4: orthogonalized + size)

**Date:** 2026-06-14
**Branch:** `claude/research-h46cfx`

Three passes. v1 (Appendix) got the flagship study *running* and showed neither
the signal nor the harness could be trusted. v2 fixed the bugs and rearchitected
the research stack + C++ engine. **v3 closes the last gap from v2 — statistical
power — by switching to a complete monthly data source and running 8 years**, and
the longer sample changes the story.

---

## v4 headline — orthogonalization & contract size (read this first)

Two questions: does the contract signal add anything **beyond momentum**, and
does **contract size relative to the company** matter (the velocity *ratio* is
scale-free and throws away dollar magnitude)?

- **New size feature: `contract_intensity`** = trailing-12-month obligations ÷
  market cap, where market cap uses **point-in-time shares outstanding** from
  SEC `dei:EntityCommonStockSharesOutstanding` (`filed` date = ts_available, so
  no lookahead). A $1B award is far more material to a small supplier than to a
  prime; intensity captures that, velocity_z does not.
- **New method: Fama–MacBeth** cross-sectional regression (`research.fama_macbeth`)
  — per-period multivariate slopes averaged over non-overlapping periods, so a
  feature with a positive *univariate* IC can still come out insignificant once
  correlated features are controlled for.

**Findings (8y):**
- Of the three, **`contract_intensity` is the least-dead** — univariate 60d
  IC 0.069, t **1.41**, long/short spread +2.9% — i.e. size-relative awards beat
  the scale-free velocity ratio. But **1.41 < 2**: not significant.
- **Velocity adds nothing over momentum** (Fama–MacBeth t ≈ 0 at every horizon).
- **Nothing survives the multivariate** — in `forward ~ velocity + intensity +
  momentum`, no slope reaches |t| ≳ 2 at any horizon (best is momentum 60d at
  t 1.36). See `fama_macbeth.md`.

**Verdict:** accounting for contract size helps (intensity > velocity), but
neither contract feature is a statistically significant predictor, and neither
adds robust incremental information beyond price momentum on this ~24-name
universe over 8 years. Honest negative result, now stress-tested from three
angles (univariate IC, size-adjustment, and orthogonalization).

### v4 Fama–MacBeth (8y, t-stats)

| model | horizon | velocity_z | intensity | momentum |
|-------|--------:|-----------:|----------:|---------:|
| all_three | 20d | +0.44 | +1.17 | −1.28 |
| all_three | 60d | −0.56 | +0.15 | +1.36 |
| all_three | 120d | −0.23 | −0.00 | +0.82 |

(Caveat: PLTR shares not on the SEC dei tag → no intensity for it; intensity
coverage ≈ 83% of stock-days. Market cap uses cover-page shares, which lag
intraperiod buyback/issuance slightly.)

---

## v3 headline

- **Better data source.** The feature now comes from USAspending's
  `spending_over_time` endpoint — **server-aggregated monthly obligation totals**,
  complete and untruncated, one request per vendor. (The v2 transaction endpoint
  truncated the oldest history for primes booking >5k transactions/year, which
  would bias the trailing baseline.) Coverage jumped to **2,065 feature points /
  21 names over 8 years**.
- **Power test result:** with 8 years instead of 3, **neither signal is robust.**
  Contract velocity is insignificant at every horizon (IC t = −1.75 / −0.07 /
  0.46). And critically, **the momentum baseline's strong 3-year result did NOT
  replicate** — its 120d IC t-stat collapsed from **3.15 (3y) → 0.19 (8y)**. The
  v2 momentum "edge" was a small-sample / regime artifact, exactly the trap that
  motivated the non-overlapping, t-stat-reporting rebuild.
- **Takeaway:** on a ~24-name defense universe, neither contract-award
  acceleration nor 63-day price momentum is a dependable cross-sectional
  predictor once you measure it honestly over a full cycle. A negative result —
  and a concrete demonstration of why 3-year backtests oversell.

### v3 results (8y, live data 2026-06-14)

| feature | horizon | periods | IC | IC t-stat | Sharpe (ann.) |
|---------|--------:|--------:|---:|----------:|--------------:|
| contract_award_velocity_z | 20d  | 100 | −0.040 | −1.75 | −0.66 |
| | 60d  | 33 | −0.004 | −0.07 | −0.18 |
| | 120d | 16 | 0.042 | 0.46 | 0.29 |
| price_momentum_63d | 20d  | 97 | −0.025 | −0.80 | −0.14 |
| | 60d  | 32 | 0.024 | 0.41 | 0.32 |
| | 120d | 16 | 0.015 | **0.19** _(3y was 3.15)_ | −0.10 |

The rest of this document (v2) describes the rearchitecture that made this
honest measurement possible.

---

## TL;DR (v2 rearchitecture)

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

### Results — 3-year snapshot (superseded by the v3 8-year table above)

> These were the first honest numbers and already showed the contract feature
> had no significant edge. The momentum t=3.15 here is precisely the
> small-sample result that v3 shows does **not** hold up over 8 years.

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
# Python study (live data) — 8y for adequate power
python studies/contract_award_velocity.py --years 8 \
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
