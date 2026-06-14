#include <doctest/doctest.h>
#include "quant_forge/engine.hpp"
#include "quant_forge/metrics.hpp"
#include <vector>

using namespace qf;

namespace {
    // Equity curve with *varying* daily returns (alternating +0.2% / +0.05%),
    // one point per day, so volatility is well-defined and Sharpe is positive.
    // (A constant-return curve has zero volatility => undefined/zero Sharpe.)
    auto sample_equity_curve() -> std::vector<std::pair<Timestamp, double>> {
        std::vector<std::pair<Timestamp, double>> curve;
        constexpr Timestamp DAY = 86'400'000'000'000LL;
        double equity = 100'000.0;
        for (int i = 0; i < 252; ++i) {
            curve.emplace_back(static_cast<Timestamp>(i) * DAY, equity);
            equity *= (i % 2 == 0) ? 1.002 : 1.0005;
        }
        return curve;
    }
}

TEST_CASE("Sharpe ratio positive on rising, varying curve") {
    auto curve = sample_equity_curve();
    double sharpe = qf::metrics::sharpe_ratio(curve);
    CHECK(sharpe > 0.0);
}

TEST_CASE("Daily volatility well-defined and positive") {
    auto curve = sample_equity_curve();
    CHECK(qf::metrics::daily_volatility_pct(curve) > 0.0);
}

TEST_CASE("Max drawdown zero on uptrend") {
    auto curve = sample_equity_curve();
    double mdd = qf::metrics::max_drawdown_pct(curve);
    CHECK(mdd == doctest::Approx(0.0));
}

TEST_CASE("Max drawdown with dip") {
    std::vector<std::pair<Timestamp, double>> curve{
        {0, 100.0}, {1, 120.0}, {2, 80.0}, {3, 110.0}
    };
    double mdd = qf::metrics::max_drawdown_pct(curve);
    // Peak at 120, trough at 80 = 33.33% drawdown
    CHECK(mdd == doctest::Approx(33.33).epsilon(0.01));
}

TEST_CASE("Realized round-trip P&L pairs entries and exits") {
    constexpr Timestamp DAY = 86'400'000'000'000LL;
    std::vector<Fill> fills{
        {1, "A", Side::Buy,  100.0, 10, 0 * DAY, 0.0, 0.0},  // open long
        {2, "A", Side::Sell, 110.0, 10, 1 * DAY, 0.0, 0.0},  // +100 win
        {3, "A", Side::Buy,  100.0, 10, 2 * DAY, 0.0, 0.0},  // open long
        {4, "A", Side::Sell,  90.0, 10, 3 * DAY, 0.0, 0.0},  // -100 loss
    };
    auto pnls = qf::metrics::realized_trade_pnls(fills);
    REQUIRE(pnls.size() == 2);
    CHECK(pnls[0] == doctest::Approx(100.0));
    CHECK(pnls[1] == doctest::Approx(-100.0));
}

TEST_CASE("Win rate and profit factor from real P&L") {
    constexpr Timestamp DAY = 86'400'000'000'000LL;
    std::vector<Fill> fills{
        {1, "A", Side::Buy,  100.0, 10, 0 * DAY, 0.0, 0.0},
        {2, "A", Side::Sell, 110.0, 10, 1 * DAY, 0.0, 0.0},  // +100
        {3, "A", Side::Buy,  100.0, 10, 2 * DAY, 0.0, 0.0},
        {4, "A", Side::Sell,  90.0, 10, 3 * DAY, 0.0, 0.0},  // -100
    };
    CHECK(qf::metrics::win_rate(fills) == doctest::Approx(50.0));
    CHECK(qf::metrics::profit_factor(fills) == doctest::Approx(1.0));
}

TEST_CASE("Win rate is zero when no positions are closed") {
    // Open-only fills realize nothing -> no trades, 0% win rate (not NaN/100%).
    std::vector<Fill> fills{
        {1, "A", Side::Buy, 100.0, 10, 0, 0.0, 0.0},
        {2, "B", Side::Buy, 100.0, 10, 0, 0.0, 0.0},
    };
    CHECK(qf::metrics::win_rate(fills) == doctest::Approx(0.0));
}

TEST_CASE("Short round trip realizes P&L with correct sign") {
    constexpr Timestamp DAY = 86'400'000'000'000LL;
    std::vector<Fill> fills{
        {1, "A", Side::Sell, 100.0, 10, 0 * DAY, 0.0, 0.0},  // open short
        {2, "A", Side::Buy,   90.0, 10, 1 * DAY, 0.0, 0.0},  // cover lower => +100
    };
    auto pnls = qf::metrics::realized_trade_pnls(fills);
    REQUIRE(pnls.size() == 1);
    CHECK(pnls[0] == doctest::Approx(100.0));
}

TEST_CASE("Annualized return") {
    double total = 28.0;  // 28% over 2 years
    double ann = qf::metrics::annualized_return_pct(total, 0, 2ULL * 31'536'000'000'000'000ULL);
    // (1.28)^(1/2) - 1 = ~13.1%
    CHECK(ann == doctest::Approx(13.14).epsilon(0.1));
}
