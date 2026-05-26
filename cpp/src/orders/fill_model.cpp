#include "quant_forge/engine.hpp"
#include <algorithm>
#include <numeric>
#include <cmath>

namespace qf {

// ── Order Fill Model ─────────────────────────────────────────────
// (already in engine.cpp — this file extends with limit/stop order logic)

namespace {

double compute_slippage(Price market_price, Volume quantity, double bps) {
    return bps / 10000.0 * market_price;
}

} // namespace

// Extended fill model for limit/stop orders
std::vector<Fill> simulate_fills(
    const std::vector<Order>& orders,
    const Bar& bar,
    const SimulationConfig& config)
{
    std::vector<Fill> fills;

    for (const auto& order : orders) {
        Price fill_price = 0.0;
        bool should_fill = false;

        switch (order.type) {
            case OrderType::Market:
                fill_price = bar.close;
                should_fill = true;
                break;
            case OrderType::Limit:
                if (order.side == Side::Buy && order.limit_price.has_value()) {
                    should_fill = bar.low <= order.limit_price.value();
                    fill_price = std::min(order.limit_price.value(), bar.open);
                } else if (order.limit_price.has_value()) {
                    should_fill = bar.high >= order.limit_price.value();
                    fill_price = std::max(order.limit_price.value(), bar.open);
                }
                break;
            case OrderType::Stop:
                if (order.side == Side::Sell && order.stop_price.has_value()) {
                    should_fill = bar.low <= order.stop_price.value();
                    fill_price = order.stop_price.value();
                } else if (order.side == Side::Buy && order.stop_price.has_value()) {
                    should_fill = bar.high >= order.stop_price.value();
                    fill_price = order.stop_price.value();
                }
                break;
            case OrderType::StopLimit:
                // Simplified: treat as stop
                if (order.side == Side::Sell && order.stop_price.has_value()) {
                    should_fill = bar.low <= order.stop_price.value();
                    fill_price = order.limit_price.value_or(order.stop_price.value());
                }
                break;
        }

        if (should_fill) {
            double slip = compute_slippage(fill_price, order.quantity, config.slippage_model_bps);
            fill_price += (order.side == Side::Buy) ? slip : -slip;

            Fill f{
                .order_id   = order.id,
                .symbol     = order.symbol,
                .side       = order.side,
                .price      = fill_price,
                .quantity   = static_cast<Volume>(order.quantity),
                .ts         = bar.ts,
                .commission = std::max(config.commission_per_share * order.quantity, config.min_commission),
                .slippage_bps = config.slippage_model_bps,
            };
            fills.push_back(f);
        }
    }

    return fills;
}

} // namespace qf
