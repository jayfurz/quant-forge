#pragma once

#include "quant_forge/types.hpp"
#include <vector>

namespace qf::metrics {

/// Compute all simulation metrics from equity curve + fills
SimulationMetrics compute_all(
    const std::vector<std::pair<Timestamp, double>>& equity_curve,
    const std::vector<Fill>& fills,
    double initial_capital,
    Timestamp start_ts,
    Timestamp end_ts);

double sharpe_ratio(const std::vector<std::pair<Timestamp, double>>& equity_curve, double risk_free_rate = 0.0);
double sortino_ratio(const std::vector<std::pair<Timestamp, double>>& equity_curve, double risk_free_rate = 0.0);
double max_drawdown_pct(const std::vector<std::pair<Timestamp, double>>& equity_curve);
/// Per-trade realized P&L (dollars, net of commission), one entry per
/// position-reducing fill, derived from average-cost round-trip accounting.
std::vector<double> realized_trade_pnls(const std::vector<Fill>& fills);
double win_rate(const std::vector<Fill>& fills);
double profit_factor(const std::vector<Fill>& fills);
double calmar_ratio(double annualized_return, const std::vector<std::pair<Timestamp, double>>& equity_curve);
double daily_volatility_pct(const std::vector<std::pair<Timestamp, double>>& equity_curve);
double annualized_return_pct(double total_return, Timestamp start, Timestamp end);

} // namespace qf::metrics
