#pragma once

#include "quant_forge/engine.hpp"
#include <functional>
#include <string>
#include <memory>

namespace qf::strategies {

// Build a momentum + EMA + hysteresis strategy.
// - Computes (close / close_lookback_days_ago - 1) as raw momentum score
// - Smooths with EMA
// - Enters long when smoothed score > upper_threshold
// - Exits when smoothed score < lower_threshold
// - Requires consecutive_bars above/below threshold for hysteresis
// - Fixed allocation per symbol: equal_weight across all symbols
struct MomentumEmaHysteresisConfig {
    int    lookback_days     = 63;
    int    ema_period        = 5;
    double upper_threshold   = 0.02;   // enter when > 2% momentum
    double lower_threshold   = -0.02;  // exit when < -2% momentum
    int    consecutive_bars  = 2;      // hysteresis: require N bars
    double max_position_pct  = 0.20;   // max 20% of equity per position
};

Strategy build_momentum_ema_hysteresis(
    const MomentumEmaHysteresisConfig& cfg,
    const std::vector<std::string>& symbols);

// Factory: build a strategy by name
// Supported names: "momentum_ema_hysteresis", "buy_and_hold"
Strategy build_strategy(
    const std::string& name,
    const std::vector<std::string>& symbols);

} // namespace qf::strategies
