# Research Notes — Contract Award Velocity Signal Study

**Date:** 2026-06-14
**Branch:** `claude/research-h46cfx`
**Scope:** Get the flagship signal study running on real data, report what it
actually shows, and audit the methodology hard enough to know whether to trust it.

---

## TL;DR

1. **The study had never run.** Three independent breaking bugs sat between the
   downloader and the study runner. I fixed all three; the pipeline now runs
   end-to-end on live Yahoo Finance + USAspending data.
2. **Two more bugs were silently corrupting the numbers** even once it ran: an
   inverted quintile sign convention (reported long/short spreads with the wrong
   sign) and a drawdown formula that produced values like **−571,992%**. Both fixed.
3. **The headline signal does not work.** With the math corrected,
   `contract_award_velocity_z` has an information coefficient of essentially
   **zero** (IC ≈ 0.002–0.014, IC-IR ≈ 0.01, positive ~50% of months — a coin flip).
   The price-momentum baseline, by contrast, shows a real cross-sectional effect.
4. **Even the "it doesn't work" conclusion is only provisional**, because the
   feature construction still contains lookahead and data-validity problems that
   I documented but deliberately did *not* paper over. A clean verdict needs the
   v2 fixes listed at the end.

This is an honest negative result on the signal plus a set of correctness fixes
to the research harness itself.

---

## What I set out to do

The repo ships a research framework (`FeatureStore` → `PointInTimeJoiner` →
`ForwardReturnLabeler` → `SignalStudyRunner`) and one flagship study,
`studies/contract_award_velocity.py`. The hypothesis: acceleration in public
defense-contract awards predicts forward returns for defense/aerospace stocks
relative to the sector ETF (`ITA`).

I ran it. It didn't work — not "no signal," but "doesn't execute." So step one
became making it actually produce a number.

---

## Part 1 — Three breaking bugs (the study had never run)

### Bug 1: Yahoo downloader is rate-limited into uselessness
`downloaders/ohlcv.py` sent `User-Agent: QuantForge/0.1`. Yahoo's v8 chart API
returns **HTTP 429** to any non-browser UA, so *every* price download failed.

**Fix:** present a standard desktop-browser User-Agent and retry 429s with
exponential backoff. Side effect: the repo's own `test_pipeline.py` live Yahoo
test, which presumably also failed before, now passes (AAPL → 81 bars).

### Bug 2: column-name contract mismatch (downloader ↔ study)
`gov_contracts.fetch_defense_contracts` normalizes the USAspending payload to
snake_case (`amount`, `vendor`, `start_date`). But `build_contract_feature`
looked for `"Award Amount"`, `"Recipient Name"`, etc. The lookup always failed:

```
[ERROR] Cannot find required columns. Available:
['vendor','award_id','agency','description','amount',...]
[ERROR] No features generated.
```

**Fix:** accept both the raw and normalized field names.

### Bug 3: `KeyError` in the drawdown calc
`SignalStudyRunner.run` read `spread["cumulative_spread"]`, but that column is
only added to the `long_short` frame:

```
polars.exceptions.ColumnNotFoundError: "cumulative_spread" not found
```

**Fix:** read from `long_short`.

> The absence of any `reports/` directory in the repo history corroborates that
> these three bugs meant the study had produced output **zero times** before now.

---

## Part 2 — Two analytical-correctness bugs (wrong numbers, no crash)

These didn't stop execution; they quietly produced misleading results.

### Bug 4: inverted quintile sign convention
The runner ranked features `descending=True` (so Q1 = highest value) but then
computed the long/short spread as `Q5 − Q1` and labeled Q5 the "top." The result
contradicted itself: the momentum baseline had **positive IC (+0.19)** but a
**negative reported spread (−12.7%)** — impossible if the labels meant what they
said. The reported spread was actually *bottom minus top*.

**Fix:** rank ascending (Q1 = lowest, Q5 = highest, conventional), so `Q5 − Q1`
is a true top-minus-bottom long/short whose sign agrees with the IC. After the
fix, momentum's spread flips to **+14.9%**, consistent with its +0.19 IC.

### Bug 5: drawdown formula divides by a near-zero peak
The long/short equity curve is an *additive* cumulative sum of per-period
spreads. The old code computed `(cum − peak) / peak.abs()`, but early in the
series the running peak is ~0, so the division exploded:

| horizon | old "max drawdown" | corrected (pp of cum. spread) |
|--------:|-------------------:|------------------------------:|
| 20d     | −3,160%            | small |
| 60d     | −7,220%            | moderate |
| 120d    | −571,993%          | −235 to −820 pp |

**Fix:** report drawdown as peak-to-trough in cumulative-spread percentage points
(additive series), not as a fraction of a near-zero peak.

---

## Part 3 — Results (after all five fixes)

Universe: 25 defense primes/suppliers, benchmark `ITA`, 3-year lookback.
Live data pulled 2026-06-14.

| feature | horizon | obs | IC (mean) | IC-IR | IC>0 % | Q5−Q1 spread | "Sharpe"* |
|---------|--------:|----:|----------:|------:|-------:|-------------:|----------:|
| **contract_award_velocity_z** | 20d  | 5,064 | 0.0017 | 0.004 | 50.2% | +0.83% | 0.94 |
| | 60d  | 4,774 | 0.0135 | 0.031 | 52.4% | +3.40% | 1.97 |
| | 120d | 4,350 | 0.0045 | 0.010 | 52.6% | +7.81% | 2.32 |
| **price_momentum_63d** (baseline) | 20d  | 16,032 | −0.0101 | −0.031 | 42.2% | +0.78% | 1.28 |
| | 60d  | 15,072 | 0.1070 | 0.360 | 62.6% | +6.24% | 5.82 |
| | 120d | 13,632 | 0.1946 | 0.691 | 72.9% | +14.95% | 9.58 |

\* The "Sharpe" column is annualized from daily, **overlapping** forward-return
windows and is badly inflated — see Caveat C. Use it only to compare signals on
equal footing, not as a tradable expectation.

### Reading the table

- **The contract signal has no edge.** IC ≈ 0 at every horizon, IC-IR ≈ 0.01,
  and it's positive ~50% of months — indistinguishable from noise. The
  superficially "nice" +7.8% 120d spread is an artifact: the Q5 bucket holds only
  **51 of 4,350 observations** (the feature is far too sparse to quintile-sort —
  see Caveat B), so that bucket's mean is dominated by a handful of names.
- **Momentum is real here, directionally.** Clean monotonic quintiles
  (Q1 11.1% → Q5 26.0% at 120d), IC +0.19, IC-IR 0.69, positive 73% of months.
  Cross-sectional momentum within defense names carried information over this
  sample. (Magnitudes still inflated by overlapping windows.)

So on a like-for-like basis, the proposed alternative-data feature is **beaten
by, and adds nothing to, a trivial price-only baseline.**

---

## Part 4 — Caveats I did NOT fix (why the verdict is still "provisional")

A negative result is only credible if the test was fair. These remain, and each
biases the feature's apparent quality — mostly *upward*, which makes the ~0 IC
even more damning, but they must be fixed before any v2 claim:

### Caveat A — lookahead in the feature value itself
1. **Full-sample z-score.** `build_contract_feature` normalizes velocity with the
   mean/std computed over the *entire* history per ticker
   (`.mean().over("symbol")`), including future observations. That is lookahead.
   Use an expanding/trailing window instead.
2. **"Award Amount" is the current total obligation.** The award-level USAspending
   endpoint returns the cumulative obligated amount *as of today*, including
   modifications booked years after the award. Stamping that figure at the
   original award date leaks the future into the past. The point-in-time-correct
   source is the **transaction-level** feed (`action_date` + per-transaction
   obligation).
3. **`ts_available = period-of-performance start_date`** is the wrong timestamp.
   Observed `start_date` values span **1984 → 2028** (verified) — PoP starts, not
   "when the award became public." Awards are also reported to FPDS with a lag, so
   the honest available-date is roughly `action_date + reporting_lag`.

### Caveat B — the universe is too sparse to sort
The feature store ended up with **100 rows across only 13 of 25 tickers** (12
names — RTX, GD, BA, … — never matched), because the downloader pulls only the
**top 100 awards by dollar amount per vendor** (`limit=100`, sorted desc) and the
rolling-velocity step then thins it further. With ~5 populated names on a typical
day, "quintiles" are degenerate (top bucket = 1 stock). You cannot run a
cross-sectional quintile study on 5 names. Either widen the universe materially or
switch to a time-series (per-name) signal test.

> Note also that `build_contract_feature` uses **row-based** rolling windows
> (`rolling_sum(window_size=90)` = 90 *award rows*, not 90 days) on a series with
> only ~5–10 rows per name. The "90-day" / "2-year" windows do not mean what their
> names say; they should be time-based (`rolling_*_by="ts_available"`).

### Caveat C — overlapping windows inflate every significance stat
Each trading day is treated as an independent "period," but a 120-day forward
return computed daily overlaps its neighbor by 119/120. The ~600 "periods" are
nowhere near 600 independent observations, so the annualized Sharpe and IC-IR are
massively overstated (this is why momentum shows a fantasy Sharpe of 9.6).
Sample at non-overlapping horizons, or apply a Newey–West / overlap correction.

### Caveat D — multiple testing
Three horizons × two features × (spread, IC, …) with no correction. Any "winner"
here would need out-of-sample and significance adjustment before being believed.

---

## Part 5 — Recommendations for v2 (prioritized)

1. **Fix the available-date and amount source** (Caveat A2/A3): pull
   transaction-level obligations with `action_date`, add a reporting lag, and set
   `ts_available` accordingly. This is the single biggest validity fix.
2. **Trailing/expanding z-score** instead of full-sample (Caveat A1).
3. **Time-based rolling windows** in the velocity calc (Caveat B note).
4. **Widen the universe or switch to time-series tests** — 13 names can't be
   quintile-sorted (Caveat B).
5. **Non-overlapping or overlap-corrected stats** for Sharpe/IC-IR (Caveat C).
6. Then, and only then, re-ask whether contract-award acceleration beats momentum.

---

## Files touched

| File | Change |
|------|--------|
| `python/downloaders/ohlcv.py` | Browser UA + 429 retry/backoff (Bug 1) |
| `studies/contract_award_velocity.py` | Accept normalized column names (Bug 2) |
| `python/research/study_runner.py` | Drawdown `KeyError` (Bug 3), quintile sign (Bug 4), additive drawdown + labels (Bug 5) |
| `.gitignore` | Ignore generated `data/features/` |

Generated artifacts for this run live alongside this file in
`reports/contract_award_velocity/{velocity,momentum_baseline}_{20,60,120}d/`.
Reproduce with:

```bash
python studies/contract_award_velocity.py --years 3 \
    --out reports/contract_award_velocity --horizons 20,60,120
```
