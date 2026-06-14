# Revenue-surprise reversal — robustness gauntlet

Naive cross-event t-stats vs **calendar-clustered** (one obs per
event-month) — the honest correction for earnings-season clustering.

## Per group (CAR)

| group/window | mean | naive t | clustered t | n |
|---|--:|--:|--:|--:|
| positive_1_20 | -0.413% | -2.06 | -1.97 | 1088 (172mo) |
| negative_1_20 | +0.253% | +1.21 | +0.72 | 1109 (168mo) |
| positive_1_60 | +0.080% | +0.23 | +0.71 | 1088 (172mo) |
| negative_1_60 | +0.993% | +2.84 | +3.24 | 1109 (168mo) |

## Long/short reversal P&L  (−sign(surprise)·CAR; >0 ⇒ reversal pays)

| window | mean | naive t | clustered t |
|---|--:|--:|--:|
| 1_20 | +0.332% | +2.29 | +1.24 |
| 1_60 | +0.473% | +1.90 | +2.29 |

## Liquidity terciles (LS reversal, [1,60], clustered t)

| tercile | mean | clustered t |
|---|--:|--:|
| low_liquidity | -0.201% | -0.50 |
| mid_liquidity | +1.143% | +1.65 |
| high_liquidity | +0.726% | +2.09 |

## Out-of-sample (LS reversal, clustered t)

| half | [1,20] | [1,60] |
|---|--:|--:|
| first_half | +0.66 | +0.59 |
| second_half | +1.26 | +2.71 |

_Clustered t is the one to trust. |t|≳2 in clustered AND out-of-sample
would make the reversal credible._
