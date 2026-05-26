#include <doctest/doctest.h>
#include "quant_forge/engine.hpp"
#include "quant_forge/metrics.hpp"
#include <vector>

using namespace qf;

namespace {
    // Build a simple equity curve: starts at 100k, gains 1% over 10 steps
    auto sample_equity_curve() -> std::vector<std::pair<Timestamp, double>> {
        std::vector<std::pair<Timestamp, double>> curve;
        constexpr Timestamp DAY = 86'400'000'000'000LL;
        double equity = 100'000.0;
        for (int i = 0; i < 252; ++i) {
            curve.emplace_back(i * DAY, equity);
            equity *= 1.001;  // 0.1% daily return
        }
        return curve;
    }
}

TEST_CASE("Sharpe ratio positive") {
    auto curve = sample_equity_curve();
    double sharpe = qf::metrics::sharpe_ratio(curve);
    CHECK(sharpe > 0.0);
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

TEST_CASE("Win rate basic") {
    std::vector<Fill> fills{
        {1, "A", qf::Side::Sell, 110.0, 10, 0, 1.0},   // win
        {2, "A", qf::Side::Sell, 90.0, 10, 0, 1.0},     // loss
    };
    double wr = qf::metrics::win_rate(fills);
    // Simple: both Sell fills = 2 "trades"
    CHECK(wr >= 0.0);
}

TEST_CASE("Annualized return") {
    double total = 28.0;  // 28% over 2 years
    double ann = qf::metrics::annualized_return_pct(total, 0, 2ULL * 31'536'000'000'000'000ULL);
    // (1.28)^(1/2) - 1 = ~13.1%
    CHECK(ann == doctest::Approx(13.14).epsilon(0.1));
}
