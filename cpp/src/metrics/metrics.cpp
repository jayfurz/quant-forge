#include "quant_forge/types.hpp"
#include <vector>
#include <cmath>
#include <algorithm>
#include <numeric>

namespace qf::metrics {

struct DailyReturn {
    Timestamp ts;
    double return_pct;
};

// Helper: compute daily returns from equity curve
inline std::vector<DailyReturn> daily_returns(
    const std::vector<std::pair<Timestamp, double>>& equity_curve)
{
    if (equity_curve.size() < 2) return {};

    // Group by day, take last equity of each day
    std::vector<DailyReturn> rets;
    constexpr Timestamp DAY_NS = 86'400'000'000'000;

    Timestamp current_day = equity_curve[0].first / DAY_NS;
    double day_open_equity = equity_curve[0].second;

    for (size_t i = 1; i < equity_curve.size(); ++i) {
        Timestamp day = equity_curve[i].first / DAY_NS;
        if (day != current_day) {
            rets.push_back({equity_curve[i].first, (equity_curve[i - 1].second - day_open_equity) / day_open_equity * 100.0});
            current_day = day;
            day_open_equity = equity_curve[i - 1].second;
        }
    }
    return rets;
}

// ── Sharpe Ratio ────────────────────────────────────────────────
inline double sharpe_ratio(const std::vector<std::pair<Timestamp, double>>& equity_curve, double risk_free_rate = 0.0) {
    auto rets = daily_returns(equity_curve);
    if (rets.size() < 2) return 0.0;

    double mean = 0.0;
    for (const auto& r : rets) mean += r.return_pct;
    mean /= static_cast<double>(rets.size());

    // Subtract daily risk-free rate
    double rf_daily = risk_free_rate / 252.0;
    mean -= rf_daily;

    double var = 0.0;
    for (const auto& r : rets) {
        double diff = r.return_pct - mean;
        var += diff * diff;
    }
    var /= static_cast<double>(rets.size()) - 1.0;
    double stddev = std::sqrt(var);

    if (stddev < 1e-10) return 0.0;
    return (mean / stddev) * std::sqrt(252.0);  // Annualize
}

// ── Sortino Ratio ───────────────────────────────────────────────
inline double sortino_ratio(const std::vector<std::pair<Timestamp, double>>& equity_curve, double risk_free_rate = 0.0) {
    auto rets = daily_returns(equity_curve);
    if (rets.size() < 2) return 0.0;

    double mean = 0.0;
    for (const auto& r : rets) mean += r.return_pct;
    mean /= static_cast<double>(rets.size());

    double rf_daily = risk_free_rate / 252.0;
    mean -= rf_daily;

    // Downside deviation only
    double downside_var = 0.0;
    size_t count = 0;
    for (const auto& r : rets) {
        double excess = r.return_pct - rf_daily;
        if (excess < 0) {
            downside_var += excess * excess;
            ++count;
        }
    }
    if (count == 0) return 0.0;
    downside_var /= static_cast<double>(count);
    double downside_dev = std::sqrt(downside_var);

    if (downside_dev < 1e-10) return 0.0;
    return (mean / downside_dev) * std::sqrt(252.0);
}

// ── Max Drawdown ────────────────────────────────────────────────
inline double max_drawdown_pct(const std::vector<std::pair<Timestamp, double>>& equity_curve) {
    if (equity_curve.empty()) return 0.0;

    double peak = equity_curve[0].second;
    double max_dd = 0.0;

    for (const auto& [ts, equity] : equity_curve) {
        if (equity > peak) peak = equity;
        double dd = (peak - equity) / peak * 100.0;
        if (dd > max_dd) max_dd = dd;
    }
    return max_dd;
}

// ── Win Rate ────────────────────────────────────────────────────
inline double win_rate(const std::vector<Fill>& fills) {
    if (fills.empty()) return 0.0;

    int wins = 0;
    std::unordered_map<uint64_t, double> order_entry_price;
    std::unordered_map<uint64_t, Side> order_side;

    for (const auto& f : fills) {
        // Group fills by order_id for multi-fill orders
        auto it = order_entry_price.find(f.order_id);
        if (it == order_entry_price.end()) {
            order_entry_price[f.order_id] = f.price;
            order_side[f.order_id] = f.side;
        } else {
            double entry = it->second;
            double pnl = (f.side == Side::Sell)
                ? (f.price - entry)
                : (entry - f.price);
            if (pnl > 0) ++wins;
        }
    }

    return static_cast<double>(wins) / static_cast<double>(fills.size()) * 100.0;
}

// ── Profit Factor ───────────────────────────────────────────────
inline double profit_factor(const std::vector<Fill>& fills) {
    double gross_profit = 0.0;
    double gross_loss = 0.0;

    // Simplified: use fills directly
    for (const auto& f : fills) {
        if (f.side == Side::Sell) {  // closing trade
            if (f.price > 0) gross_profit += f.price;
            else gross_loss += -f.price;
        }
    }

    if (gross_loss < 1e-10) return gross_profit > 0 ? 999.0 : 0.0;
    return gross_profit / gross_loss;
}

// ── Calmar Ratio ────────────────────────────────────────────────
inline double calmar_ratio(
    double annualized_return_pct,
    const std::vector<std::pair<Timestamp, double>>& equity_curve)
{
    double mdd = max_drawdown_pct(equity_curve);
    if (mdd < 1e-10) return 0.0;
    return annualized_return_pct / mdd;
}

// ── Portfolio-level daily volatility ────────────────────────────
inline double daily_volatility_pct(
    const std::vector<std::pair<Timestamp, double>>& equity_curve)
{
    auto rets = daily_returns(equity_curve);
    if (rets.size() < 2) return 0.0;

    double mean = 0.0;
    for (const auto& r : rets) mean += r.return_pct;
    mean /= static_cast<double>(rets.size());

    double var = 0.0;
    for (const auto& r : rets) {
        double diff = r.return_pct - mean;
        var += diff * diff;
    }
    var /= static_cast<double>(rets.size()) - 1.0;
    return std::sqrt(var);
}

// ── Annualized Return ──────────────────────────────────────────
inline double annualized_return_pct(
    double total_return_pct, Timestamp start_ts, Timestamp end_ts)
{
    if (end_ts <= start_ts) return 0.0;
    constexpr Timestamp YEAR_NS = 31'536'000'000'000'000ULL;
    double years = static_cast<double>(end_ts - start_ts) / static_cast<double>(YEAR_NS);
    if (years < 1e-10) return 0.0;
    return (std::pow(1.0 + total_return_pct / 100.0, 1.0 / years) - 1.0) * 100.0;
}

// ── Full metrics computation ────────────────────────────────────
inline SimulationMetrics compute_all(
    const std::vector<std::pair<Timestamp, double>>& equity_curve,
    const std::vector<Fill>& fills,
    double initial_capital,
    Timestamp start_ts,
    Timestamp end_ts)
{
    double total_ret = 0.0;
    if (initial_capital > 0 && !equity_curve.empty()) {
        total_ret = (equity_curve.back().second - initial_capital) / initial_capital * 100.0;
    }

    double ann_ret = annualized_return_pct(total_ret, start_ts, end_ts);
    double sharpe = sharpe_ratio(equity_curve);
    double sortino = sortino_ratio(equity_curve);
    double mdd = max_drawdown_pct(equity_curve);
    double wr = win_rate(fills);
    double pf = profit_factor(fills);
    double calmar = calmar_ratio(ann_ret, equity_curve);
    double vol = daily_volatility_pct(equity_curve);

    int wins = 0, losses = 0;
    for (const auto& f : fills) {
        // Crude classification
        if (f.side == Side::Sell) ++wins;
    }
    losses = static_cast<int>(fills.size()) - wins;

    return SimulationMetrics{
        .total_return_pct       = total_ret,
        .annualized_return_pct  = ann_ret,
        .sharpe_ratio           = sharpe,
        .sortino_ratio          = sortino,
        .max_drawdown_pct       = mdd,
        .win_rate_pct           = wr,
        .profit_factor          = pf,
        .avg_trade_pnl          = total_ret / std::max(1, static_cast<int>(fills.size())),
        .total_trades           = static_cast<int>(fills.size()),
        .winning_trades         = wins,
        .losing_trades          = losses,
        .calmar_ratio           = calmar,
        .daily_volatility_pct   = vol,
    };
}

} // namespace qf::metrics
