#include <doctest/doctest.h>
#include "quant_forge/engine.hpp"
#include <cmath>

using namespace qf;

TEST_CASE("Fill model: market order") {
    SimulationConfig config;
    Bar bar{0, 100.0, 105.0, 95.0, 102.0, 10000};

    Order market{1, "AAPL", Side::Buy, OrderType::Market, TimeInForce::Day, 50};
    auto fills = simulate_fills({market}, bar, config);

    CHECK(fills.size() == 1);
    CHECK(fills[0].price == doctest::Approx(102.0));
    CHECK(fills[0].quantity == 50);
}

TEST_CASE("Fill model: limit order fills") {
    SimulationConfig config;
    Bar bar{0, 100.0, 105.0, 95.0, 102.0, 10000};

    Order buy_limit{1, "AAPL", Side::Buy, OrderType::Limit, TimeInForce::Day, 50, 96.0};
    auto fills = simulate_fills({buy_limit}, bar, config);
    // Low was 95, limit is 96 → should fill at min(96, 100) = 96 + slippage
    CHECK(!fills.empty());
}

TEST_CASE("Fill model: limit order misses") {
    SimulationConfig config;
    Bar bar{0, 100.0, 102.0, 98.0, 101.0, 10000};

    Order buy_limit{1, "AAPL", Side::Buy, OrderType::Limit, TimeInForce::Day, 50, 90.0};
    auto fills = simulate_fills({buy_limit}, bar, config);
    CHECK(fills.empty());  // Low was 98, limit 90 → no fill
}

TEST_CASE("Fill model: stop order triggered") {
    SimulationConfig config;
    Bar bar{0, 100.0, 105.0, 93.0, 95.0, 10000};

    Order sell_stop{1, "AAPL", Side::Sell, OrderType::Stop, TimeInForce::Day, 50, std::nullopt, 94.0};
    auto fills = simulate_fills({sell_stop}, bar, config);
    // Low (93) pierced stop (94) → should fill
    CHECK(!fills.empty());
}
