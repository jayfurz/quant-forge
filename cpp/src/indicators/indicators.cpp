#include "quant_forge/indicators.hpp"
#include <cmath>
#include <algorithm>
#include <numeric>
#include <stdexcept>

namespace qf::indicators {

// ── SMA ─────────────────────────────────────────────────────────
void SMA::push(double price) {
    values.push_back(price);
    if (values.size() > period) {
        values.erase(values.begin());
    }
}

std::optional<double> SMA::current() const {
    if (values.size() < period) return std::nullopt;
    return std::accumulate(values.begin(), values.end(), 0.0) / static_cast<double>(values.size());
}

std::vector<double> SMA::compute(std::span<const double> prices) const {
    std::vector<double> out(prices.size());
    sma_vectorized(prices.data(), out.data(), prices.size(), period);
    return out;
}

// ── EMA ─────────────────────────────────────────────────────────
EMA::EMA(size_t p) : period(p), alpha(2.0 / static_cast<double>(p + 1)) {}

void EMA::push(double price) {
    if (!current_value.has_value()) {
        current_value = price;
    } else {
        current_value = alpha * price + (1.0 - alpha) * current_value.value();
    }
}

std::optional<double> EMA::current() const {
    return current_value;
}

std::vector<double> EMA::compute(std::span<const double> prices) const {
    std::vector<double> out(prices.size());
    ema_vectorized(prices.data(), out.data(), prices.size(), period);
    return out;
}

// ── RSI ─────────────────────────────────────────────────────────
void RSI::push(double price, double prev_price) {
    double change = price - prev_price;
    double gain = change > 0 ? change : 0.0;
    double loss = change < 0 ? -change : 0.0;

    if (gains.size() < period) {
        gains.push_back(gain);
        losses.push_back(loss);
        if (gains.size() == period) {
            avg_gain = std::accumulate(gains.begin(), gains.end(), 0.0) / period;
            avg_loss = std::accumulate(losses.begin(), losses.end(), 0.0) / period;
        }
    } else {
        avg_gain = (avg_gain * (period - 1) + gain) / period;
        avg_loss = (avg_loss * (period - 1) + loss) / period;
    }
}

std::optional<double> RSI::current() const {
    // Flat series (no gains and no losses): RSI is undefined; return the
    // neutral 50 rather than 100. (The old order returned 100 here because the
    // avg_loss==0 check fired first, so the both-zero branch was dead code.)
    if (avg_gain == 0.0 && avg_loss == 0.0) return 50.0;
    if (avg_loss == 0.0) return 100.0;
    double rs = avg_gain / avg_loss;
    return 100.0 - (100.0 / (1.0 + rs));
}

std::vector<double> RSI::compute(std::span<const double> prices) const {
    std::vector<double> out(prices.size(), 0.0);
    if (prices.size() <= 1) return out;

    RSI temp{period};
    for (size_t i = 1; i < prices.size(); ++i) {
        temp.push(prices[i], prices[i - 1]);
        auto val = temp.current();
        out[i] = val.value_or(50.0);
    }
    return out;
}

// ── Bollinger Bands ─────────────────────────────────────────────
void BollingerBands::push(double price) {
    sma.push(price);
    // stddev computed lazily in current()
}

std::optional<BollingerBands::Result> BollingerBands::current() const {
    if (sma.values.size() < period) return std::nullopt;

    double mean = std::accumulate(sma.values.begin(), sma.values.end(), 0.0) /
                  static_cast<double>(sma.values.size());
    double sq_sum = 0.0;
    for (double v : sma.values) {
        sq_sum += (v - mean) * (v - mean);
    }
    double stddev = std::sqrt(sq_sum / static_cast<double>(sma.values.size()));

    return Result{
        .middle = mean,
        .upper  = mean + multiplier * stddev,
        .lower  = mean - multiplier * stddev,
        .width  = 2.0 * multiplier * stddev
    };
}

// ── MACD ────────────────────────────────────────────────────────
void MACD::push(double price) {
    fast.push(price);
    slow.push(price);
    if (auto f = fast.current(); f.has_value()) {
        if (auto s = slow.current(); s.has_value()) {
            signal.push(f.value() - s.value());
        }
    }
}

std::optional<MACD::Result> MACD::current() const {
    auto f = fast.current();
    auto s = slow.current();
    auto sig = signal.current();
    if (!f || !s || !sig) return std::nullopt;

    double macd_line = f.value() - s.value();
    return Result{
        .macd_line   = macd_line,
        .signal_line = sig.value(),
        .histogram   = macd_line - sig.value()
    };
}

// ── ATR ─────────────────────────────────────────────────────────
void ATR::push(double high, double low, double close) {
    if (previous_close.has_value()) {
        double tr = std::max({
            high - low,
            std::abs(high - previous_close.value()),
            std::abs(low - previous_close.value())
        });
        tr_ema.push(tr);
    }
    previous_close = close;
}

std::optional<double> ATR::current() const {
    return tr_ema.current();
}

// ── Vectorized ─────────────────────────────────────────────────
void sma_vectorized(const double* prices, double* output,
                     size_t len, size_t period) {
    if (len < period) {
        std::fill(output, output + len, 0.0);
        return;
    }

    double window_sum = std::accumulate(prices, prices + period, 0.0);
    for (size_t i = 0; i < period - 1; ++i) output[i] = 0.0;

    output[period - 1] = window_sum / static_cast<double>(period);
    for (size_t i = period; i < len; ++i) {
        window_sum += prices[i] - prices[i - period];
        output[i] = window_sum / static_cast<double>(period);
    }
}

void ema_vectorized(const double* prices, double* output,
                     size_t len, size_t period) {
    if (len == 0) return;
    double alpha = 2.0 / static_cast<double>(period + 1);
    output[0] = prices[0];
    for (size_t i = 1; i < len; ++i) {
        output[i] = alpha * prices[i] + (1.0 - alpha) * output[i - 1];
    }
}

} // namespace qf::indicators
