#pragma once

#include "quant_forge/types.hpp"
#include <vector>
#include <span>
#include <optional>

namespace qf::indicators {

// ── Simple Moving Average ────────────────────────────────────────
struct SMA {
    size_t period;
    std::vector<double> values;

    void push(double price);
    [[nodiscard]] std::optional<double> current() const;
    [[nodiscard]] std::vector<double> compute(std::span<const double> prices) const;
};

// ── Exponential Moving Average ───────────────────────────────────
struct EMA {
    size_t period;
    double alpha;   // 2 / (period + 1)
    std::optional<double> current_value;

    explicit EMA(size_t period);
    void push(double price);
    [[nodiscard]] std::optional<double> current() const;
    [[nodiscard]] std::vector<double> compute(std::span<const double> prices) const;
};

// ── Relative Strength Index ──────────────────────────────────────
struct RSI {
    size_t period = 14;
    std::vector<double> gains;
    std::vector<double> losses;
    double avg_gain = 0.0;
    double avg_loss = 0.0;

    void push(double price, double prev_price);
    [[nodiscard]] std::optional<double> current() const;
    [[nodiscard]] std::vector<double> compute(std::span<const double> prices) const;
};

// ── Bollinger Bands ──────────────────────────────────────────────
struct BollingerBands {
    size_t period = 20;
    double multiplier = 2.0;
    SMA sma{period};

    void push(double price);
    struct Result {
        double middle;  // SMA
        double upper;   // middle + multiplier * stddev
        double lower;   // middle - multiplier * stddev
        double width;   // upper - lower (volatility proxy)
    };
    [[nodiscard]] std::optional<Result> current() const;
};

// ── MACD ────────────────────────────────────────────────────────
struct MACD {
    size_t fast_period   = 12;
    size_t slow_period   = 26;
    size_t signal_period = 9;

    EMA fast{fast_period};
    EMA slow{slow_period};
    EMA signal{signal_period};

    void push(double price);
    struct Result {
        double macd_line;
        double signal_line;
        double histogram;  // macd_line - signal_line
    };
    [[nodiscard]] std::optional<Result> current() const;
};

// ── ATR (Average True Range) ────────────────────────────────────
struct ATR {
    size_t period = 14;
    std::optional<double> previous_close;
    EMA tr_ema{period};

    void push(double high, double low, double close);
    [[nodiscard]] std::optional<double> current() const;
};

// ── Utility: Vectorized SMA (for backtesting speed) ─────────────
void sma_vectorized(const double* prices, double* output,
                     size_t len, size_t period);

void ema_vectorized(const double* prices, double* output,
                     size_t len, size_t period);

} // namespace qf::indicators
