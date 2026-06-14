# Contract Award — Event Study

**Events:** 1010 large awards (≥ $50M), defense universe, vs ITA.
**Window:** [−5, +60] trading days. CAR = cumulative abnormal return (stock − sector ETF).

## CAR by window

| window | n | mean CAR | t-stat | hit rate |
|--------|--:|---------:|-------:|---------:|
| [-5,-1] | 1005 | +0.032% | +0.30 | 50% |
| [0,0] | 1007 | -0.034% | -0.58 | 48% |
| [1,5] | 1009 | -0.022% | -0.19 | 48% |
| [1,20] | 1006 | -0.236% | -1.14 | 49% |
| [1,60] | 998 | -0.926% | -2.37 | 49% |

## Post-event drift [1,20] by award size

| size | n | mean CAR | t-stat | hit rate |
|------|--:|---------:|-------:|---------:|
| small | 334 | +0.277% | +0.76 | 53% |
| mid | 335 | -0.569% | -1.73 | 46% |
| large | 337 | -0.413% | -1.10 | 48% |

_CAAR curve in `caar.csv`. Post-event windows [+1,…] are the
tradeable part; [−5,−1] is descriptive run-up._
