#include <doctest/doctest.h>
#include "quant_forge/engine.hpp"

using namespace qf;

TEST_CASE("Portfolio mark-to-market") {
    SimulationConfig config{.initial_capital = 100000.0};
    Portfolio portfolio(config);

    // Buy 100 shares of AAPL at $150
    Fill buy{
        .order_id = 1,
        .symbol = "AAPL",
        .side = Side::Buy,
        .price = 150.0,
        .quantity = 100,
        .commission = 1.0
    };
    portfolio.apply_fill(buy);

    // Mark at $160
    portfolio.mark_to_market({{"AAPL", 160.0}});
    CHECK(portfolio.equity() == doctest::Approx(100000.0 - 15000.0 - 1.0 + 16000.0));
}

TEST_CASE("Portfolio position close") {
    SimulationConfig config{.initial_capital = 100000.0};
    Portfolio portfolio(config);

    // Buy
    Fill buy{1, "AAPL", Side::Buy, 100.0, 100, 1};
    portfolio.apply_fill(buy);

    // Sell (close)
    Fill sell{2, "AAPL", Side::Sell, 110.0, 100, 1};
    portfolio.apply_fill(sell);

    // Position should be gone
    CHECK(portfolio.account().positions.empty());
}

TEST_CASE("Order fill slippage") {
    SimulationConfig config{.slippage_model_bps = 2.0};
    OrderManager om(config);

    Order buy{1, "AAPL", Side::Buy, OrderType::Market, TimeInForce::Day, 100};
    auto fill = om.submit(buy, 150.0, 0);

    // 2 bps slippage on buy: 150 * 1.0002 = 150.03
    CHECK(fill.price == doctest::Approx(150.0 * 1.0002));
    CHECK(fill.slippage_bps == doctest::Approx(2.0));
}

TEST_CASE("Simulation engine empty run") {
    SimulationConfig config;
    SimulationEngine engine(config);

    MarketDataStore store;
    engine.load_data(std::move(store));

    auto metrics = engine.run();
    CHECK(metrics.total_return_pct == doctest::Approx(0.0));
}
