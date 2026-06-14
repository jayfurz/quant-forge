# Research Notes — Fundamental Momentum

**Date:** 2026-06-14 · **Branch:** `claude/research-h46cfx`

A fresh hypothesis after the federal-contract arc (a clean null). Fundamental
momentum / PEAD is a *documented* anomaly, so it doubles as a check that the
platform can find a signal that is actually there.

## Setup

- **Universe:** ~100 sector-diversified large/mid caps (86 with usable XBRL
  revenue), benchmark SPY, 8 years.
- **Data:** SEC XBRL revenue via company-concept, stamped point-in-time at the
  SEC `filed` date (`downloaders.sec_edgar.fetch_revenue_quarterly`).
- **Features** (`research.build_fundamental_momentum`): `rev_yoy_growth`
  (revenue vs same fiscal quarter a year earlier) and `rev_yoy_accel` (change in
  that growth). ~90-day periods only; first-filing-wins (no restatement
  lookahead). Coverage 87% / 77% of stock-days.
- **Method:** quintiles + IC and Fama–MacBeth vs price momentum, non-overlapping.

## Result (cross-sectional): no significant edge

Fama–MacBeth t-stats, `forward ~ accel + growth + momentum`:

| horizon | n | rev_yoy_accel | rev_yoy_growth | momentum |
|--------:|--:|--------------:|---------------:|---------:|
| 20d  | 97 | −0.48 | +1.06 | +0.90 |
| 60d  | 32 | +1.33 | +0.19 | +1.13 |
| 120d | 16 | +0.69 | −1.04 | +1.60 |

Nothing clears |t|≈2. Revenue growth/acceleration tilts mildly positive at short
horizons but is not significant; price momentum is the strongest (120d t=1.60)
yet still short of significance on this 86-name, 8-year large-cap sample.

## Why this is the wrong *frame* (next step)

The documented fundamental-momentum effect is **PEAD — post-earnings-announcement
drift**: an *event-time* reaction/drift around the earnings release, strongest in
the days/weeks after, and historically in smaller caps. A slow cross-sectional
rank at arbitrary 20/60/120-day rebalances is not where it lives, and the 10-Q
*filing* date lags the earnings *announcement* (the surprise is partly priced by
the time the 10-Q is filed). So the natural follow-up is an **event study around
the revenue-growth surprise**, split by surprise sign — reusing
`research.EventStudy` exactly as in the contract arc.

_Reproduce:_ `python studies/fundamental_momentum.py --years 8`

---

## Addendum — PEAD event study (`studies/earnings_drift.py`)

Re-framed as event-time: abnormal return (stock − SPY) after each quarterly
report, split by revenue-acceleration sign. 2,197 events (1,088 positive / 1,109
negative).

| window | positive CAR | negative CAR | spread (pos−neg) |
|--------|-------------:|-------------:|-----------------:|
| [−5,−1] | +0.263% (t=+1.78) | −0.122% | +0.385% |
| [0,0]   | +0.123% | −0.127% | +0.250% |
| [1,5]   | −0.077% | +0.139% | −0.217% |
| [1,20]  | **−0.413% (t=−2.06)** | +0.253% | −0.667% |
| [1,60]  | +0.080% | **+0.993% (t=+2.84)** | −0.913% |

**The sign is *reversal*, not drift.** Accelerating-revenue names run up *before*
the 10-Q (the earnings announcement precedes the filing — note the +0.26% pre
window), then underperform over the next 1–3 months; decelerating names do the
opposite. This is the opposite of textbook PEAD and consistent with short-horizon
**post-announcement reversal** in large caps.

**Caveat (don't trade this yet):** the most-significant cells (neg [1,60]
t=+2.84, pos [1,20] t=−2.06) rest on cross-event t-stats that assume
independence, but earnings cluster in 2–3 week "seasons", so many names' windows
overlap and share a common factor SPY-adjustment doesn't fully remove — exactly
the inflation the contract event study exposed (where t=−5.2 collapsed to −1.9
after de-overlapping). A proper test needs calendar-cluster-robust standard
errors / a non-overlapping season sample. Treat the reversal as **suggestive,
not established** — but it's the most interesting effect found so far and a clear
next target.

_Reproduce:_ `python studies/earnings_drift.py`

---

## Robustness gauntlet on the reversal (`studies/earnings_drift_robust.py`)

The reversal got the full treatment that killed every prior "signal": calendar-
clustered standard errors, a long/short P&L, a liquidity split, and an
out-of-sample temporal split.

**1. Calendar-clustered t (one obs per event-month).** This is where the contract
event drift died (t=−5.2 → −1.9). The reversal mostly *survives* it:

| component | naive t | clustered t |
|-----------|--------:|------------:|
| positive surprise, [1,20] | −2.06 | −1.97 |
| negative surprise, [1,60] | +2.84 | **+3.24** |
| **long/short reversal, [1,60]** | +1.90 | **+2.29** |
| long/short reversal, [1,20] | +2.29 | +1.24 |

So clustering doesn't explain it away — the 60-day reversal is real *in sample*
(clustered t≈2.3, driven by decelerating-revenue names drifting **up**).

**2. Out-of-sample (the decisive test) — it fails.** The entire effect is
second-half-only:

| half | LS [1,20] | LS [1,60] |
|------|----------:|----------:|
| 2018–2022 | +0.66 | **+0.59** |
| 2022–2026 | +1.26 | **+2.71** |

A stable effect should appear in both halves; this one is absent pre-2022 and
concentrated post-2022 — regime-dependent, not dependable.

**3. Liquidity — wrong sign for the behavioral story.** The reversal lives in
*liquid* large caps (high-liquidity clustered t=+2.09) and is absent in the
least-liquid tercile (−0.50). Overreaction-reversal is supposed to be strongest
in illiquid names, so this looks more like a recent large-cap rotation than a
behavioral mispricing.

### Verdict
The revenue-surprise reversal is the **strongest candidate the project found** —
it's the only effect to survive calendar-clustering (clustered t≈2.3). But it
**fails the out-of-sample split** (entirely post-2022) and has the wrong
liquidity signature, so it is **not an established, tradeable edge** — it joins
contract velocity, momentum, event drift, and contract intensity in the
"dissolves under the right test" column. The pattern is now overwhelming: on
these universes and this decade, every apparent signal is either an artifact or
regime-specific. That consistency is itself the result — and the platform's
gauntlet (PIT → non-overlap → orthogonalization → cluster-robust → OOS) reliably
finds it.

_Reproduce:_ `python studies/earnings_drift_robust.py`


