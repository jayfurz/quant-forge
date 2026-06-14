# Out-of-sample validation — contract_intensity

Fama–MacBeth `forward ~ velocity + intensity + momentum`. Each cell is
the **intensity** coefficient t-stat (the signal under test).

| split | 20d | 60d |
|---|---|---|
| full sample | t=+2.24 (n=95) | t=+1.57 (n=32) |
| in-sample (1st half) | t=+2.41 (n=48) | t=+0.95 (n=16) |
| **OOS (2nd half)** | t=+0.15 (n=48) | t=+1.26 (n=16) |
| universe A (even) | t=+0.84 (n=95) | t=+0.26 (n=32) |
| universe B (odd) | t=+2.34 (n=95) | t=+2.16 (n=32) |

_Each split halves the data, so t-stats shrink with √n; look for
consistent sign/magnitude, not |t|>2 in every cell._
