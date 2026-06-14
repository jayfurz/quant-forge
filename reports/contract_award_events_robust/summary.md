# Contract Award — Event Study

**Events:** 297 large awards (≥ $50M), defense universe, vs ITA.
**Window:** [−5, +60] trading days. CAR = cumulative abnormal return (stock − sector ETF).

## CAR by window

| window | n | mean CAR | t-stat | hit rate |
|--------|--:|---------:|-------:|---------:|
| [-5,-1] | 292 | +0.034% | +0.17 | 50% |
| [0,0] | 294 | -0.137% | -1.19 | 49% |
| [1,5] | 296 | +0.417% | +1.86 | 54% |
| [1,20] | 296 | +0.290% | +0.71 | 54% |
| [1,60] | 291 | -0.223% | -0.27 | 53% |

## Post-event drift [1,20] by award size

| size | n | mean CAR | t-stat | hit rate |
|------|--:|---------:|-------:|---------:|
| small | 98 | +1.627% | +2.02 | 61% |
| mid | 99 | -0.381% | -0.65 | 54% |
| large | 99 | -0.362% | -0.52 | 48% |

_CAAR curve in `caar.csv`. Post-event windows [+1,…] are the
tradeable part; [−5,−1] is descriptive run-up._
