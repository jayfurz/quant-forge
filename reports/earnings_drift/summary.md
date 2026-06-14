# Revenue-Surprise Drift (PEAD) — Event Study

Surprise = `rev_yoy_accel` (revenue YoY acceleration). Abnormal return vs SPY, window [−5, +60]. Event = SEC filing date.

### Positive surprises (accel > 0) (n=1088)

| window | n | mean CAR | t-stat | hit |
|---|--:|--:|--:|--:|
| [-5,-1] | 824 | +0.263% | +1.78 | 51% |
| [0,0] | 824 | +0.123% | +0.87 | 50% |
| [1,5] | 1087 | -0.077% | -0.61 | 49% |
| [1,20] | 1079 | -0.413% | -2.06 | 46% |
| [1,60] | 1031 | +0.080% | +0.23 | 47% |

### Negative surprises (accel < 0) (n=1109)

| window | n | mean CAR | t-stat | hit |
|---|--:|--:|--:|--:|
| [-5,-1] | 850 | -0.122% | -0.85 | 49% |
| [0,0] | 850 | -0.127% | -0.96 | 47% |
| [1,5] | 1109 | +0.139% | +1.15 | 50% |
| [1,20] | 1107 | +0.253% | +1.21 | 49% |
| [1,60] | 1095 | +0.993% | +2.84 | 51% |

### All events (n=2197)

| window | n | mean CAR | t-stat | hit |
|---|--:|--:|--:|--:|
| [-5,-1] | 1674 | +0.067% | +0.65 | 50% |
| [0,0] | 1674 | -0.004% | -0.04 | 49% |
| [1,5] | 2196 | +0.032% | +0.37 | 49% |
| [1,20] | 2186 | -0.076% | -0.52 | 47% |
| [1,60] | 2126 | +0.550% | +2.21 | 49% |

## Positive − Negative drift (read-across)

| window | pos CAR | neg CAR | spread |
|---|--:|--:|--:|
| [-5,-1] | +0.263% | -0.122% | +0.385% |
| [0,0] | +0.123% | -0.127% | +0.250% |
| [1,5] | -0.077% | +0.139% | -0.217% |
| [1,20] | -0.413% | +0.253% | -0.667% |
| [1,60] | +0.080% | +0.993% | -0.913% |

_Quarterly events ~63 trading days apart, so 60d windows barely
overlap within a name (unlike the contract event study). t-stats are
cross-event; calendar clustering across names remains, mitigated by
the SPY adjustment. Filing date lags the announcement → lower bound._
