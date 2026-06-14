# Fama–MacBeth — incremental predictive power

Cross-sectional regression of forward return on standardized features,
averaged across non-overlapping periods. `t` is the Fama–MacBeth t-stat
(|t| ≳ 2 ⇒ the feature adds information beyond the others).

## velocity_vs_momentum

| horizon | n | contract_award_velocity_z | price_momentum_63d |
|---|---|---|---|
| 20d | 97 | b=+0.019, t=+0.13 | b=+0.077, t=+0.24 |
| 60d | 32 | b=-0.635, t=-1.27 | b=+0.928, t=+0.65 |
| 120d | 16 | b=-0.943, t=-0.92 | b=+0.190, t=+0.12 |

## intensity_vs_momentum

| horizon | n | contract_intensity | price_momentum_63d |
|---|---|---|---|
| 20d | 97 | b=+0.382, t=+1.94 | b=+0.095, t=+0.30 |
| 60d | 32 | b=+1.854, t=+1.26 | b=-0.407, t=-0.43 |
| 120d | 16 | b=+1.241, t=+1.17 | b=-0.233, t=-0.15 |

## all_three

| horizon | n | contract_award_velocity_z | contract_intensity | price_momentum_63d |
|---|---|---|---|---|
| 20d | 97 | b=-0.037, t=-0.24 | b=+0.450, t=+2.11 | b=+0.114, t=+0.34 |
| 60d | 32 | b=-0.588, t=-1.18 | b=+2.312, t=+1.57 | b=-0.099, t=-0.10 |
| 120d | 16 | b=-1.190, t=-0.95 | b=+1.536, t=+1.44 | b=+0.258, t=+0.17 |

