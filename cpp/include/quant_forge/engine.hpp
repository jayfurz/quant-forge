#pragma once

#include "quant_forge/types.hpp"
#include <unordered_map>
#include <vector>
#include <queue>
#include <functional>
#include <string>
#include <stdexcept>

namespace qf {

class MarketDataStore {
public:
    void load_bars(const std::string& symbol, const std::vector<Bar>& bars);
    void load_csv(const std::string& symbol, const std::string& path);

    // Get all bars for a symbol sorted by timestamp
    [[nodiscard]] std::vector<Bar> bars_for(const std::string& symbol) const;

    // Get a slice between [start_ts, end_ts]
    [[nodiscard]] std::vector<Bar> bars_in_range(
        const std::string& symbol, Timestamp start, Timestamp end) const;

    [[nodiscard]] Timestamp earliest_ts() const;
    [[nodiscard]] Timestamp latest_ts() const;
    [[nodiscard]] const std::vector<std::string>& symbols() const { return symbol_list_; }

private:
    std::unordered_map<std::string, std::vector<Bar>> bars_{};
    std::vector<std::string> symbol_list_;
};

class OrderManager {
public:
    explicit OrderManager(const SimulationConfig& config);

    [[nodiscard]] Fill submit(const Order& order, Price current_price, Timestamp ts);

    void cancel(uint64_t order_id);

    [[nodiscard]] const std::vector<Fill>& fills() const { return fills_; }
    [[nodiscard]] const std::vector<Order>& open_orders() const { return open_orders_; }

private:
    [[nodiscard]] Fill fill_order(const Order& order, Price market_price, Timestamp ts);

    const SimulationConfig& config_;
    std::vector<Order> open_orders_;
    std::vector<Fill> fills_;
    uint64_t fill_id_counter_ = 1;
};

class Portfolio {
public:
    explicit Portfolio(const SimulationConfig& config);

    void apply_fill(const Fill& fill);
    void mark_to_market(const std::unordered_map<std::string, Price>& prices);

    [[nodiscard]] const Account& account() const { return account_; }
    [[nodiscard]] double equity() const;
    [[nodiscard]] double buying_power() const;  // cash + margin available

private:
    Account account_;
    const SimulationConfig& config_;
};

// The engine evaluates strategies once per (symbol, bar). `symbol` identifies
// which instrument `recent_bars` belongs to — without it a multi-symbol
// strategy cannot keep per-symbol state and ends up cross-contaminating
// signals across instruments.
using StrategyFunc = std::function<std::vector<Signal>(
    const std::string& symbol,
    const std::vector<Bar>& recent_bars,
    const Account& account
)>;

struct Strategy {
    std::string    id;
    StrategyFunc   generate_signals;
    BarSize        bar_size;
    std::vector<std::string> symbols;
};

class SimulationEngine {
public:
    explicit SimulationEngine(const SimulationConfig& config);

    void load_data(MarketDataStore store);
    void register_strategy(Strategy strategy);
    void set_commission_model(std::function<double(const Fill&)> model);

    [[nodiscard]] SimulationMetrics run();

    [[nodiscard]] const std::vector<Fill>& fills() const;
    [[nodiscard]] const std::vector<std::pair<Timestamp, double>>& equity_curve() const;
    [[nodiscard]] const SimulationMetrics& metrics() const;

private:
    void step_bar(const std::string& symbol, const Bar& bar, Timestamp ts);
    SimulationMetrics compute_metrics() const;

    SimulationConfig config_;
    MarketDataStore data_store_;
    OrderManager order_manager_;
    Portfolio portfolio_;
    std::vector<Strategy> strategies_;
    std::function<double(const Fill&)> commission_model_;

    std::vector<Fill> fills_;
    std::vector<std::pair<Timestamp, double>> equity_curve_;
    SimulationMetrics metrics_;
    bool metrics_dirty_ = true;
};

// Free function: fill simulation for limit/stop orders (in fill_model.cpp)
std::vector<Fill> simulate_fills(
    const std::vector<Order>& orders,
    const Bar& bar,
    const SimulationConfig& config);

// Free function: parse a multi-symbol bars CSV file
// Returns map of symbol → sorted bars. Throws on validation failure.
// Expected columns: symbol,timestamp,open,high,low,close,volume
std::unordered_map<std::string, std::vector<Bar>> parse_bars_csv(const std::string& path);

} // namespace qf
