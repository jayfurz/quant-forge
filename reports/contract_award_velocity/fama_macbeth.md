# Fama–MacBeth — incremental predictive power

Cross-sectional regression of forward return on standardized features,
averaged across non-overlapping periods. `t` is the Fama–MacBeth t-stat
(|t| ≳ 2 ⇒ the feature adds information beyond the others).

## velocity_vs_momentum

| horizon | n | contract_award_velocity_z | price_momentum_63d |
|---|---|---|---|
| 20d | 97 | b=-0.030, t=-0.18 | b=-0.081, t=-0.29 |
| 60d | 32 | b=-0.262, t=-0.62 | b=+1.346, t=+1.30 |
| 120d | 16 | b=-0.235, t=-0.30 | b=+1.813, t=+0.90 |

## intensity_vs_momentum

| horizon | n | contract_intensity | price_momentum_63d |
|---|---|---|---|
| 20d | 97 | b=+0.313, t=+1.17 | b=-0.173, t=-0.60 |
| 60d | 32 | b=+0.337, t=+0.71 | b=+1.084, t=+1.09 |
| 120d | 16 | b=-0.131, t=-0.14 | b=+1.115, t=+0.55 |

## all_three

| horizon | n | contract_award_velocity_z | contract_intensity | price_momentum_63d |
|---|---|---|---|---|
| 20d | 97 | b=+0.079, t=+0.44 | b=+0.362, t=+1.17 | b=-0.377, t=-1.28 |
| 60d | 32 | b=-0.245, t=-0.56 | b=+0.092, t=+0.15 | b=+1.548, t=+1.36 |
| 120d | 16 | b=-0.195, t=-0.23 | b=-0.004, t=-0.00 | b=+1.578, t=+0.82 |

