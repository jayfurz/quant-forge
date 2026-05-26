#pragma once

#include <string>
#include <string_view>
#include <vector>
#include <variant>
#include <optional>
#include <cstdint>

namespace qf {

using Price    = double;
using Volume   = int64_t;
using Timestamp = int64_t;  // nanosecond epoch

// ── Market Data ──────────────────────────────────────────────────
enum class BarSize { T1s, T1m, T5m, T15m, T1h, T1d, T1w };

struct Bar {
    Timestamp ts;
    Price     open;
    Price     high;
    Price     low;
    Price     close;
    Volume    volume;
};

struct Quote {
    Timestamp ts;
    Price     bid;
    Price     ask;
    Volume    bid_size;
    Volume    ask_size;
};

struct Trade {
    Timestamp ts;
    Price     price;
    Volume    size;
    std::string exchange;
};

using MarketTick = std::variant<Bar, Quote, Trade>;

// ── Orders & Fills ───────────────────────────────────────────────
enum class Side { Buy, Sell };
enum class OrderType { Market, Limit, Stop, StopLimit };
enum class TimeInForce { Day, GTC, IOC, FOK };

struct Order {
    uint64_t      id;
    std::string   symbol;
    Side          side;
    OrderType     type;
    TimeInForce   tif;
    double        quantity;
    std::optional<Price> limit_price;
    std::optional<Price> stop_price;
    Timestamp     created_at;
    std::string   strategy_id;  // which strategy sent this
};

struct Fill {
    uint64_t  order_id;
    std::string symbol;
    Side      side;
    Price     price;
    Volume    quantity;
    Timestamp ts;
    double    commission;
    double    slippage_bps;  // basis points of slippage
};

// ── Portfolio State ──────────────────────────────────────────────
struct Position {
    std::string symbol;
    double      quantity;       // signed: positive = long, negative = short
    Price       avg_entry;      // weighted average cost basis
    Price       last_price;
    double      unrealized_pnl;
    double      realized_pnl;
};

struct Account {
    double      cash;
    double      initial_capital;
    double      equity;          // cash + positions mark-to-market
    double      margin_used;
    std::vector<Position> positions;
};

// ── Signal / Strategy Output ─────────────────────────────────────
struct Signal {
    std::string strategy_id;
    std::string symbol;
    double      target_weight;   // -1.0 to 1.0, where 1.0 = full long
    double      confidence;      // 0.0 to 1.0
    Timestamp  ts;
};

// ── Config ───────────────────────────────────────────────────────
struct SimulationConfig {
    double initial_capital    = 100'000.0;
    double commission_per_share = 0.005;
    double min_commission     = 1.0;
    double slippage_model_bps = 1.0;    // per-trade slippage basis points
    bool   shorting_enabled   = false;
    double margin_rate        = 0.30;   // 30% margin requirement
    Timestamp start_ts        = 0;
    Timestamp end_ts          = 0;
    std::vector<std::string> symbols;
    BarSize bar_size          = BarSize::T1d;
};

// ── Metrics ──────────────────────────────────────────────────────
struct SimulationMetrics {
    double total_return_pct;
    double annualized_return_pct;
    double sharpe_ratio;
    double sortino_ratio;
    double max_drawdown_pct;
    double win_rate_pct;
    double profit_factor;
    double avg_trade_pnl;
    int    total_trades;
    int    winning_trades;
    int    losing_trades;
    double calmar_ratio;
    double daily_volatility_pct;
};

} // namespace qf
