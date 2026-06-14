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
