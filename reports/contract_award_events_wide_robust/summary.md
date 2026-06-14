# Contract Award — Event Study

**Events:** 422 large awards (≥ $50M), defense universe, vs ITA.
**Window:** [−5, +60] trading days. CAR = cumulative abnormal return (stock − sector ETF).

## CAR by window

| window | n | mean CAR | t-stat | hit rate |
|--------|--:|---------:|-------:|---------:|
| [-5,-1] | 399 | +0.045% | +0.25 | 50% |
| [0,0] | 401 | -0.075% | -0.81 | 50% |
| [1,5] | 421 | +0.014% | +0.07 | 51% |
| [1,20] | 421 | +0.492% | +1.39 | 56% |
| [1,60] | 413 | -1.398% | -1.94 | 49% |

## Post-event drift [1,20] by award size

| size | n | mean CAR | t-stat | hit rate |
|------|--:|---------:|-------:|---------:|
| small | 140 | +1.438% | +2.19 | 62% |
| mid | 140 | +0.290% | +0.47 | 58% |
| large | 141 | -0.247% | -0.45 | 48% |

_CAAR curve in `caar.csv`. Post-event windows [+1,…] are the
tradeable part; [−5,−1] is descriptive run-up._
