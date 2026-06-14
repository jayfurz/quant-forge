#include "quant_forge/types.hpp"
#include <vector>
#include <cmath>
#include <algorithm>
#include <numeric>
#include <unordered_map>

namespace qf::metrics {

struct DailyReturn {
    Timestamp ts;
    double return_pct;
};

// Helper: compute daily returns from equity curve
std::vector<DailyReturn> daily_returns(
    const std::vector<std::pair<Timestamp, double>>& equity_curve)
{
    if (equity_curve.size() < 2) return {};

    // Collapse the curve to one (timestamp, equity) point per calendar day:
    // the last observation of each day.
    constexpr Timestamp DAY_NS = 86'400'000'000'000;
    std::vector<std::pair<Timestamp, double>> day_close;

    Timestamp current_day = equity_curve[0].first / DAY_NS;
    std::pair<Timestamp, double> last = equity_curve[0];
    for (size_t i = 1; i < equity_curve.size(); ++i) {
        Timestamp day = equity_curve[i].first / DAY_NS;
        if (day != current_day) {
            day_close.push_back(last);          // close of the day that ended
            current_day = day;
        }
        last = equity_curve[i];
    }
    day_close.push_back(last);                   // close of the final day

    // One return per consecutive pair of daily closes (close-to-close).
    std::vector<DailyReturn> rets;
    for (size_t i = 1; i < day_close.size(); ++i) {
        double prev = day_close[i - 1].second;
        if (prev == 0.0) continue;
        rets.push_back({day_close[i].first,
                        (day_close[i].second - prev) / prev * 100.0});
    }
    return rets;
}

// ── Sharpe Ratio ────────────────────────────────────────────────
double sharpe_ratio(const std::vector<std::pair<Timestamp, double>>& equity_curve, double risk_free_rate = 0.0) {
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
double sortino_ratio(const std::vector<std::pair<Timestamp, double>>& equity_curve, double risk_free_rate = 0.0) {
    auto rets = daily_returns(equity_curve);
    if (rets.size() < 2) return 0.0;

    double mean = 0.0;
    for (const auto& r : rets) mean += r.return_pct;
    mean /= static_cast<double>(rets.size());

    double rf_daily = risk_free_rate / 252.0;
    mean -= rf_daily;

    // Downside deviation around the (risk-free) target. The sum of squared
    // shortfalls is divided by the TOTAL number of observations, not just the
    // count of losing days — dividing by the loser count overstates Sortino.
    double downside_var = 0.0;
    size_t losers = 0;
    for (const auto& r : rets) {
        double shortfall = r.return_pct - rf_daily;
        if (shortfall < 0) {
            downside_var += shortfall * shortfall;
            ++losers;
        }
    }
    if (losers == 0) return 0.0;
    downside_var /= static_cast<double>(rets.size());
    double downside_dev = std::sqrt(downside_var);

    if (downside_dev < 1e-10) return 0.0;
    return (mean / downside_dev) * std::sqrt(252.0);
}

// ── Max Drawdown ────────────────────────────────────────────────
double max_drawdown_pct(const std::vector<std::pair<Timestamp, double>>& equity_curve) {
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

// ── Realized round-trip P&L ──────────────────────────────────────
// Walk the fills per symbol (chronologically) maintaining a signed position
// with an average cost basis. Every fill that REDUCES or CLOSES an existing
// position realizes a P&L (in dollars, net of that fill's commission). The
// resulting list is the basis for win rate, profit factor, trade counts and
// average trade P&L — all of which were previously computed from nonsense
// (e.g. treating a sell price as "profit").
std::vector<double> realized_trade_pnls(const std::vector<Fill>& fills) {
    std::vector<Fill> sorted = fills;
    std::stable_sort(sorted.begin(), sorted.end(),
                     [](const Fill& a, const Fill& b) { return a.ts < b.ts; });

    struct Pos { double qty = 0.0; double avg = 0.0; };
    std::unordered_map<std::string, Pos> book;
    std::vector<double> pnls;

    for (const auto& f : sorted) {
        Pos& p = book[f.symbol];
        double signed_qty = (f.side == Side::Buy) ? static_cast<double>(f.quantity)
                                                  : -static_cast<double>(f.quantity);

        const bool same_dir = (p.qty == 0.0) || ((p.qty > 0) == (signed_qty > 0));
        if (same_dir) {
            // Opening or adding: update weighted-average entry price.
            double new_qty = p.qty + signed_qty;
            if (new_qty != 0.0) {
                p.avg = (p.avg * std::abs(p.qty) + f.price * std::abs(signed_qty))
                        / std::abs(new_qty);
            }
            p.qty = new_qty;
        } else {
            // Reducing/closing/flipping: realize P&L on the closed quantity.
            double closing = std::min(std::abs(signed_qty), std::abs(p.qty));
            double pnl = (p.qty > 0) ? (f.price - p.avg) * closing   // long, sold
                                     : (p.avg - f.price) * closing;  // short, covered
            pnl -= f.commission;
            pnls.push_back(pnl);

            double remaining = std::abs(signed_qty) - std::abs(p.qty);
            p.qty += signed_qty;
            if (remaining > 0) {
                // Position flipped through zero; the surplus opens a new one.
                p.avg = f.price;
                p.qty = (signed_qty > 0) ? remaining : -remaining;
            }
        }
    }
    return pnls;
}

// ── Win Rate ────────────────────────────────────────────────────
double win_rate(const std::vector<Fill>& fills) {
    auto pnls = realized_trade_pnls(fills);
    if (pnls.empty()) return 0.0;
    int wins = 0;
    for (double p : pnls) if (p > 0) ++wins;
    return static_cast<double>(wins) / static_cast<double>(pnls.size()) * 100.0;
}

// ── Profit Factor ───────────────────────────────────────────────
double profit_factor(const std::vector<Fill>& fills) {
    double gross_profit = 0.0;
    double gross_loss = 0.0;
    for (double p : realized_trade_pnls(fills)) {
        if (p >= 0) gross_profit += p;
        else gross_loss += -p;
    }
    if (gross_loss < 1e-10) return gross_profit > 0 ? 999.0 : 0.0;
    return gross_profit / gross_loss;
}

// ── Calmar Ratio ────────────────────────────────────────────────
double calmar_ratio(
    double annualized_return_pct,
    const std::vector<std::pair<Timestamp, double>>& equity_curve)
{
    double mdd = max_drawdown_pct(equity_curve);
    if (mdd < 1e-10) return 0.0;
    return annualized_return_pct / mdd;
}

// ── Portfolio-level daily volatility ────────────────────────────
double daily_volatility_pct(
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
double annualized_return_pct(
    double total_return_pct, Timestamp start_ts, Timestamp end_ts)
{
    if (end_ts <= start_ts) return 0.0;
    constexpr Timestamp YEAR_NS = 31'536'000'000'000'000ULL;
    double years = static_cast<double>(end_ts - start_ts) / static_cast<double>(YEAR_NS);
    if (years < 1e-10) return 0.0;
    return (std::pow(1.0 + total_return_pct / 100.0, 1.0 / years) - 1.0) * 100.0;
}

// ── Full metrics computation ────────────────────────────────────
SimulationMetrics compute_all(
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

    // Classify by realized round-trip P&L, not by side. A "trade" is a
    // position-reducing fill; total_trades = winners + losers + breakevens.
    auto pnls = realized_trade_pnls(fills);
    int wins = 0, losses = 0;
    double total_pnl = 0.0;
    for (double p : pnls) {
        total_pnl += p;
        if (p > 0) ++wins;
        else if (p < 0) ++losses;
    }
    int closed_trades = static_cast<int>(pnls.size());
    double avg_pnl = closed_trades > 0 ? total_pnl / closed_trades : 0.0;

    return SimulationMetrics{
        .total_return_pct       = total_ret,
        .annualized_return_pct  = ann_ret,
        .sharpe_ratio           = sharpe,
        .sortino_ratio          = sortino,
        .max_drawdown_pct       = mdd,
        .win_rate_pct           = wr,
        .profit_factor          = pf,
        .avg_trade_pnl          = avg_pnl,
        .total_trades           = closed_trades,
        .winning_trades         = wins,
        .losing_trades          = losses,
        .calmar_ratio           = calmar,
        .daily_volatility_pct   = vol,
    };
}

} // namespace qf::metrics
