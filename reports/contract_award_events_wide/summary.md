# Contract Award — Event Study

**Events:** 1340 large awards (≥ $50M), defense universe, vs ITA.
**Window:** [−5, +60] trading days. CAR = cumulative abnormal return (stock − sector ETF).

## CAR by window

| window | n | mean CAR | t-stat | hit rate |
|--------|--:|---------:|-------:|---------:|
| [-5,-1] | 1266 | +0.011% | +0.11 | 50% |
| [0,0] | 1269 | +0.028% | +0.51 | 49% |
| [1,5] | 1339 | -0.493% | -4.27 | 46% |
| [1,20] | 1333 | +0.102% | +0.56 | 53% |
| [1,60] | 1321 | -1.879% | -5.17 | 47% |

## Post-event drift [1,20] by award size

| size | n | mean CAR | t-stat | hit rate |
|------|--:|---------:|-------:|---------:|
| small | 444 | +0.819% | +2.50 | 59% |
| mid | 444 | -0.101% | -0.34 | 51% |
| large | 445 | -0.412% | -1.29 | 48% |

_CAAR curve in `caar.csv`. Post-event windows [+1,…] are the
tradeable part; [−5,−1] is descriptive run-up._
