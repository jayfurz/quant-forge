#include "quant_forge/strategies.hpp"
#include <unordered_map>
#include <unordered_set>
#include <cmath>
#include <algorithm>

namespace qf::strategies {

namespace {

class MomentumEmaHysteresisStrategy {
public:
    MomentumEmaHysteresisStrategy(
        const MomentumEmaHysteresisConfig& cfg,
        const std::vector<std::string>& symbols)
        : cfg_(cfg)
    {
        for (const auto& sym : symbols) {
            state_[sym] = PerSymbolState{};
        }
    }

    std::vector<Signal> operator()(
        const std::string& symbol,
        const std::vector<Bar>& recent_bars,
        const Account& account)
    {
        if (recent_bars.size() < static_cast<size_t>(cfg_.lookback_days + 1)) {
            return {}; // Not enough data
        }

        // The engine tells us exactly which symbol this call is for, so we
        // update and act on only that symbol's state — no cross-symbol leakage.
        PerSymbolState& s = state_[symbol];

        double current_close = recent_bars.back().close;
        double past_close = recent_bars[recent_bars.size() - 1 - cfg_.lookback_days].close;
        if (past_close <= 0.0) return {};

        double momentum = (current_close / past_close) - 1.0;

        // Update the momentum EMA for this symbol.
        if (s.ema_initialized) {
            s.ema_value += (momentum - s.ema_value) * (2.0 / (cfg_.ema_period + 1));
        } else {
            s.ema_value = momentum;
            s.ema_initialized = true;
        }

        // Hysteresis: require N consecutive bars beyond a threshold.
        if (s.ema_value > cfg_.upper_threshold) {
            s.bars_above++;
            s.bars_below = 0;
        } else if (s.ema_value < cfg_.lower_threshold) {
            s.bars_below++;
            s.bars_above = 0;
        } else {
            s.bars_above = 0;
            s.bars_below = 0;
        }

        double equity = account.equity > 0 ? account.equity : account.initial_capital;

        std::vector<Signal> signals;

        // Entry — only if flat on this symbol.
        if (!s.has_position && s.bars_above >= cfg_.consecutive_bars) {
            double equity_per_symbol = equity / static_cast<double>(state_.size());
            double target_weight = equity_per_symbol / (current_close * 100.0);
            signals.push_back(Signal{
                .strategy_id   = "momentum_ema_hysteresis",
                .symbol        = symbol,
                .target_weight = std::min(1.0, target_weight),
                .confidence    = std::min(1.0, s.ema_value / (cfg_.upper_threshold * 2)),
                .ts            = recent_bars.back().ts,
            });
            s.has_position = true;
        }

        // Exit — close the existing position on this symbol.
        if (s.has_position && s.bars_below >= cfg_.consecutive_bars) {
            for (const auto& pos : account.positions) {
                if (pos.symbol == symbol && std::abs(pos.quantity) > 0) {
                    signals.push_back(Signal{
                        .strategy_id   = "momentum_ema_hysteresis",
                        .symbol        = symbol,
                        .target_weight = -std::abs(pos.quantity) / 100.0,
                        .confidence    = std::min(1.0, std::abs(s.ema_value) / (std::abs(cfg_.lower_threshold) * 2)),
                        .ts            = recent_bars.back().ts,
                    });
                    break;
                }
            }
            s.has_position = false;
        }

        return signals;
    }

private:
    struct PerSymbolState {
        double ema_value = 0.0;
        bool   ema_initialized = false;
        int    bars_above = 0;
        int    bars_below = 0;
        bool   has_position = false;  // track locally to avoid churn
    };

    MomentumEmaHysteresisConfig cfg_;
    std::unordered_map<std::string, PerSymbolState> state_;
};

class BuyAndHoldStrategy {
public:
    explicit BuyAndHoldStrategy(const std::vector<std::string>& symbols)
        : symbols_(symbols) {}

    std::vector<Signal> operator()(
        const std::string& symbol,
        const std::vector<Bar>& recent_bars,
        const Account& account)
    {
        // Buy each symbol once, on its own first bar, using that symbol's own
        // price (the old version sized every symbol off whichever symbol's
        // first bar arrived first).
        if (recent_bars.empty() || entered_.count(symbol)) return {};
        entered_.insert(symbol);

        double equity = account.equity > 0 ? account.equity : account.initial_capital;
        double per_symbol = equity / static_cast<double>(symbols_.size());
        double target_weight = per_symbol / (recent_bars.back().close * 100.0);

        return {Signal{
            .strategy_id   = "buy_and_hold",
            .symbol        = symbol,
            .target_weight = std::min(1.0, target_weight),
            .confidence    = 1.0,
            .ts            = recent_bars.back().ts,
        }};
    }

private:
    std::vector<std::string> symbols_;
    std::unordered_set<std::string> entered_;
};

} // anonymous namespace

Strategy build_momentum_ema_hysteresis(
    const MomentumEmaHysteresisConfig& cfg,
    const std::vector<std::string>& symbols)
{
    auto strat = std::make_shared<MomentumEmaHysteresisStrategy>(cfg, symbols);
    return Strategy{
        .id = "momentum_ema_hysteresis",
        .generate_signals = [strat](const std::string& sym,
                                    const std::vector<Bar>& bars,
                                    const Account& acct) {
            return (*strat)(sym, bars, acct);
        },
        .bar_size = BarSize::T1d,
        .symbols = symbols,
    };
}

Strategy build_strategy(
    const std::string& name,
    const std::vector<std::string>& symbols)
{
    if (name == "momentum_ema_hysteresis") {
        return build_momentum_ema_hysteresis(MomentumEmaHysteresisConfig{}, symbols);
    }
    if (name == "buy_and_hold") {
        auto strat = std::make_shared<BuyAndHoldStrategy>(symbols);
        return Strategy{
            .id = "buy_and_hold",
            .generate_signals = [strat](const std::string& sym,
                                        const std::vector<Bar>& bars,
                                        const Account& acct) {
                return (*strat)(sym, bars, acct);
            },
            .bar_size = BarSize::T1d,
            .symbols = symbols,
        };
    }
    throw std::runtime_error("Unknown strategy: " + name);
}

} // namespace qf::strategies
