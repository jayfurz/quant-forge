#include "quant_forge/engine.hpp"
#include <algorithm>
#include <stdexcept>

namespace qf {

// ── MarketDataStore ──────────────────────────────────────────────
void MarketDataStore::load_bars(const std::string& symbol, const std::vector<Bar>& bars_input) {
    auto copy = bars_input;
    std::ranges::sort(copy, [](const Bar& a, const Bar& b) { return a.ts < b.ts; });
    bars_[symbol] = std::move(copy);
    if (std::ranges::find(symbol_list_, symbol) == symbol_list_.end()) {
        symbol_list_.push_back(symbol);
    }
}

std::vector<Bar> MarketDataStore::bars_for(const std::string& symbol) const {
    auto it = bars_.find(symbol);
    return (it != bars_.end()) ? it->second : std::vector<Bar>{};
}

std::vector<Bar> MarketDataStore::bars_in_range(
    const std::string& symbol, Timestamp start, Timestamp end) const
{
    auto it = bars_.find(symbol);
    if (it == bars_.end()) return {};

    std::vector<Bar> result;
    for (const auto& bar : it->second) {
        if (bar.ts >= start && bar.ts <= end) result.push_back(bar);
    }
    return result;
}

Timestamp MarketDataStore::earliest_ts() const {
    Timestamp earliest = INT64_MAX;
    for (const auto& [_, v] : bars_) {
        if (!v.empty()) earliest = std::min(earliest, v[0].ts);
    }
    return earliest == INT64_MAX ? 0 : earliest;
}

Timestamp MarketDataStore::latest_ts() const {
    Timestamp latest = 0;
    for (const auto& [_, v] : bars_) {
        if (!v.empty()) latest = std::max(latest, v.back().ts);
    }
    return latest;
}

// ── OrderManager ─────────────────────────────────────────────────
OrderManager::OrderManager(const SimulationConfig& config) : config_(config) {}

Fill OrderManager::submit(const Order& order, Price current_price, Timestamp ts) {
    return fill_order(order, current_price, ts);
}

void OrderManager::cancel(uint64_t order_id) {
    std::erase_if(open_orders_, [order_id](const Order& o) { return o.id == order_id; });
}

Fill OrderManager::fill_order(const Order& order, Price market_price, Timestamp ts) {
    double slippage = config_.slippage_model_bps / 10000.0;
    Price fill_price = (order.side == Side::Buy)
        ? market_price * (1.0 + slippage)
        : market_price * (1.0 - slippage);

    double commission = std::max(
        config_.commission_per_share * order.quantity,
        config_.min_commission
    );

    Fill fill{
        .order_id   = order.id,
        .symbol     = order.symbol,
        .side       = order.side,
        .price      = fill_price,
        .quantity   = static_cast<Volume>(order.quantity),
        .ts         = ts,
        .commission = commission,
        .slippage_bps = config_.slippage_model_bps
    };

    fills_.push_back(fill);
    return fill;
}

// ── Portfolio ────────────────────────────────────────────────────
Portfolio::Portfolio(const SimulationConfig& config)
    : config_(config)
{
    account_.cash = config.initial_capital;
    account_.initial_capital = config.initial_capital;
    account_.equity = config.initial_capital;
}

void Portfolio::apply_fill(const Fill& fill) {
    double fill_value = fill.price * fill.quantity;
    double commission = fill.commission;
    double signed_quant = (fill.side == Side::Buy) ? fill.quantity : -fill.quantity;

    // Update position
    auto it = std::find_if(account_.positions.begin(), account_.positions.end(),
        [&](const Position& p) { return p.symbol == fill.symbol; });

    if (it != account_.positions.end()) {
        // Adjust existing position
        double old_qty = it->quantity;
        double new_qty = old_qty + signed_quant;

        if (std::abs(new_qty) < 1e-10) {
            // Position closed
            it->realized_pnl += (fill.price - it->avg_entry) * signed_quant;
            account_.positions.erase(it);
        } else {
            // Average cost basis update
            if ((old_qty > 0 && signed_quant > 0) || (old_qty < 0 && signed_quant < 0)) {
                it->avg_entry = (it->avg_entry * old_qty + fill.price * signed_quant) / new_qty;
            } else {
                // Partial close: realized P&L
                if (old_qty > 0) {
                    it->realized_pnl += (fill.price - it->avg_entry) * -signed_quant;
                } else {
                    it->realized_pnl += (it->avg_entry - fill.price) * signed_quant;
                }
            }
            it->quantity = new_qty;
        }
    } else {
        // New position
        account_.positions.push_back(Position{
            .symbol     = fill.symbol,
            .quantity   = signed_quant,
            .avg_entry  = fill.price,
            .last_price = fill.price,
        });
    }

    account_.cash -= fill_value * (fill.side == Side::Buy ? 1.0 : -1.0) + commission;
}

void Portfolio::mark_to_market(const std::unordered_map<std::string, Price>& prices) {
    double position_value = 0.0;
    double total_realized = 0.0;

    for (auto& pos : account_.positions) {
        auto it = prices.find(pos.symbol);
        if (it != prices.end()) {
            pos.last_price = it->second;
            pos.unrealized_pnl = (pos.last_price - pos.avg_entry) * pos.quantity;
            position_value += pos.last_price * pos.quantity;
        }
        total_realized += pos.realized_pnl;
    }

    account_.equity = account_.cash + position_value;
}

double Portfolio::equity() const { return account_.equity; }

double Portfolio::buying_power() const {
    return account_.cash + account_.equity * (1.0 - config_.margin_rate);
}

// ── SimulationEngine ─────────────────────────────────────────────
SimulationEngine::SimulationEngine(const SimulationConfig& config)
    : config_(config), order_manager_(config), portfolio_(config)
{}

void SimulationEngine::load_data(MarketDataStore store) {
    data_store_ = std::move(store);
}

void SimulationEngine::register_strategy(Strategy strategy) {
    strategies_.push_back(std::move(strategy));
}

void SimulationEngine::set_commission_model(std::function<double(const Fill&)> model) {
    commission_model_ = std::move(model);
}

SimulationMetrics SimulationEngine::run() {
    Timestamp start = config_.start_ts;
    Timestamp end = config_.end_ts;

    if (start == 0) start = data_store_.earliest_ts();
    if (end == 0) end = data_store_.latest_ts();

    // Collect all bars across symbols in timestamp order
    struct TimestampEvent {
        Timestamp ts;
        std::string symbol;
        Bar bar;
    };

    std::vector<TimestampEvent> events;
    for (const auto& sym : data_store_.symbols()) {
        auto bars = data_store_.bars_in_range(sym, start, end);
        for (const auto& b : bars) {
            events.push_back({b.ts, sym, b});
        }
    }

    std::ranges::sort(events, [](const auto& a, const auto& b) { return a.ts < b.ts; });

    // Main simulation loop
    for (const auto& evt : events) {
        step_bar(evt.symbol, evt.bar, evt.ts);
        equity_curve_.emplace_back(evt.ts, portfolio_.equity());
    }

    metrics_ = compute_metrics();
    metrics_dirty_ = false;
    return metrics_;
}

void SimulationEngine::step_bar(const std::string& symbol, const Bar& bar, Timestamp ts) {
    // Mark portfolio to market
    std::unordered_map<std::string, Price> prices{{symbol, bar.close}};
    portfolio_.mark_to_market(prices);

    // Run strategies
    for (auto& strategy : strategies_) {
        auto recent_bars = data_store_.bars_in_range(symbol, 0, ts);
        auto signals = strategy.generate_signals(recent_bars, portfolio_.account());

        for (const auto& signal : signals) {
            // Simple signal → order translation (demo)
            if (signal.target_weight == 0.0) continue;

            Order order{
                .id = static_cast<uint64_t>(fills_.size() + 1),
                .symbol = signal.symbol,
                .side = (signal.target_weight > 0) ? Side::Buy : Side::Sell,
                .type = OrderType::Market,
                .tif = TimeInForce::Day,
                .quantity = std::abs(signal.target_weight) * 100, // demo sizing
                .created_at = ts,
                .strategy_id = signal.strategy_id,
            };

            auto fill = order_manager_.submit(order, bar.close, ts);
            portfolio_.apply_fill(fill);
            fills_.push_back(fill);
        }
    }
}

SimulationMetrics SimulationEngine::compute_metrics() const {
    // Placeholder — detailed metrics in metrics source files
    double total_return = 0.0;
    if (config_.initial_capital > 0) {
        double final_equity = equity_curve_.empty()
            ? config_.initial_capital
            : equity_curve_.back().second;
        total_return = (final_equity - config_.initial_capital) / config_.initial_capital * 100.0;
    }

    return SimulationMetrics{
        .total_return_pct = total_return,
    };
}

const std::vector<Fill>& SimulationEngine::fills() const { return fills_; }
const SimulationMetrics& SimulationEngine::metrics() const { return metrics_; }
const std::vector<std::pair<Timestamp, double>>& SimulationEngine::equity_curve() const {
    return equity_curve_;
}

} // namespace qf
