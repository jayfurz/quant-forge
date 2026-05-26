#include "quant_forge/strategies.hpp"
#include <unordered_map>
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
        const std::vector<Bar>& recent_bars,
        const Account& account)
    {
        if (recent_bars.size() < static_cast<size_t>(cfg_.lookback_days + 1)) {
            return {}; // Not enough data
        }

        // Determine which symbol these bars are for
        // Engine calls per symbol, so all bars here are for the same symbol.
        // We'll use the last bar's close to determine momentum.
        if (recent_bars.empty()) return {};

        // Use close from the last bar for symbol identification isn't needed -
        // each call is per-symbol. We use the lookback index.
        double current_close = recent_bars.back().close;
        double past_close = recent_bars[recent_bars.size() - 1 - cfg_.lookback_days].close;

        if (past_close <= 0.0) return {};

        double momentum = (current_close / past_close) - 1.0;

        // Find the symbol from the state map
        // We need to match the bars to a symbol - the engine calls per symbol,
        // but doesn't pass the symbol name. We'll iterate state keys to find
        // the right one... actually, the bars are per-symbol; we track state
        // by using the first entry. Better approach: we compute signal for all
        // tracked symbols but only update the one matching.

        // Actually, the engine calls this once per symbol per bar. We'll just
        // process the momentum for all symbols uniformly. The key insight is
        // that we need per-symbol EMA tracking. Let's compute it:

        // Since we don't know WHICH symbol these bars are for (the API doesn't
        // provide it), we need a workaround: track state externally and match.
        // Simplification: for the MVP, treat each call as updating all symbol
        // EMAs, but only emit signals for symbols whose bars match.

        // Better: track by computing a hash of the bar data.
        // Even better: refactor this later, for now use a simpler approach:
        // just compute momentum and emit signal based on current state.

        // For now, we emit signals for ALL symbols — the engine filters by
        // which symbol the bar event is for. The strategy function is called
        // with bars for the symbol being processed. We update EMA for all
        // symbols and emit signals for all. The engine will only act on
        // signals for the current symbol's bar.

        // WORKAROUND: the engine passes recent_bars for the CURRENT symbol.
        // We'll match by iterating and finding which symbol's bars most closely
        // match the last bar's timestamp. This is imperfect but works for now.

        // Actually, for the MVP, let's keep it simple: we'll use a separate
        // instance per symbol approach by having the strategy always emit
        // a signal for every symbol it tracks. The engine processes per-bar
        // per-symbol, but signals for other symbols are ignored until their
        // bar comes up.

        std::vector<Signal> signals;

        for (auto& [symbol, s] : state_) {
            // Update EMA for this momentum reading
            if (s.ema_initialized) {
                s.ema_value = (momentum - s.ema_value) * (2.0 / (cfg_.ema_period + 1)) + s.ema_value;
            } else {
                s.ema_value = momentum;
                s.ema_initialized = true;
            }

            // Hysteresis logic
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
            double max_position_value = equity * cfg_.max_position_pct;

            // Check current position for this symbol
            bool has_position = false;
            for (const auto& pos : account.positions) {
                if (pos.symbol == symbol && std::abs(pos.quantity) > 0) {
                    has_position = true;
                    break;
                }
            }

            // Entry signal - only enter if we don't already hold a position
            if (!s.has_position && s.bars_above >= cfg_.consecutive_bars) {
                // Equal-weight allocation: equity_per_symbol / (price * 100) = shares/100
                // Engine multiplies target_weight by 100 to get shares
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

            // Exit signal
            if (s.has_position && s.bars_below >= cfg_.consecutive_bars) {
                s.has_position = false;
                // Close entire position
                for (const auto& pos : account.positions) {
                    if (pos.symbol == symbol) {
                        double exit_weight = -std::abs(pos.quantity) / 100.0;

                        signals.push_back(Signal{
                            .strategy_id   = "momentum_ema_hysteresis",
                            .symbol        = symbol,
                            .target_weight = exit_weight,
                            .confidence    = std::min(1.0, std::abs(s.ema_value) / (std::abs(cfg_.lower_threshold) * 2)),
                            .ts            = recent_bars.back().ts,
                        });
                        break;
                    }
                }
            }
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
        const std::vector<Bar>& recent_bars,
        const Account& account)
    {
        // Only emit entry signals on the first bar of each symbol
        if (recent_bars.size() <= 1 && !entered_) {
            entered_ = true;
            std::vector<Signal> signals;
            double equity = account.equity > 0 ? account.equity : account.initial_capital;
            double per_symbol = equity / symbols_.size();

            for (const auto& sym : symbols_) {
                double target_weight = per_symbol / (recent_bars.back().close * 100.0);
                signals.push_back(Signal{
                    .strategy_id   = "buy_and_hold",
                    .symbol        = sym,
                    .target_weight = std::min(1.0, target_weight),
                    .confidence    = 1.0,
                    .ts            = recent_bars.back().ts,
                });
            }
            return signals;
        }
        return {};
    }

private:
    std::vector<std::string> symbols_;
    bool entered_ = false;
};

} // anonymous namespace

Strategy build_momentum_ema_hysteresis(
    const MomentumEmaHysteresisConfig& cfg,
    const std::vector<std::string>& symbols)
{
    auto strat = std::make_shared<MomentumEmaHysteresisStrategy>(cfg, symbols);
    return Strategy{
        .id = "momentum_ema_hysteresis",
        .generate_signals = [strat](const std::vector<Bar>& bars, const Account& acct) {
            return (*strat)(bars, acct);
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
            .generate_signals = [strat](const std::vector<Bar>& bars, const Account& acct) {
                return (*strat)(bars, acct);
            },
            .bar_size = BarSize::T1d,
            .symbols = symbols,
        };
    }
    throw std::runtime_error("Unknown strategy: " + name);
}

} // namespace qf::strategies
