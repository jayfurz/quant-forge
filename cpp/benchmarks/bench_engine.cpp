#include <benchmark/benchmark.h>
#include "quant_forge/engine.hpp"
#include <vector>

using namespace qf;

// Build synthetic OHLCV for benchmarking
static std::vector<Bar> synthetic_bars(size_t n, double start_price = 100.0) {
    std::vector<Bar> bars;
    std::mt19937 rng(42);
    std::normal_distribution<double> ret(0.0005, 0.02);  // mean 5bp, std 2%

    double price = start_price;
    for (size_t i = 0; i < n; ++i) {
        double r = ret(rng);
        double open = price;
        double close = price * (1.0 + r);
        double high = std::max(open, close) * (1.0 + std::abs(r) * 0.5);
        double low = std::min(open, close) * (1.0 - std::abs(r) * 0.5);
        bars.push_back({static_cast<Timestamp>(i), open, high, low, close, 1'000'000});
        price = close;
    }
    return bars;
}

static void BM_simulation_10k_bars(benchmark::State& state) {
    auto bars = synthetic_bars(10'000);

    for (auto _ : state) {
        SimulationConfig config{
            .initial_capital = 100'000.0,
            .symbols = {"SYNTH"}
        };

        MarketDataStore store;
        store.load_bars("SYNTH", bars);

        SimulationEngine engine(config);
        engine.load_data(std::move(store));

        auto metrics = engine.run();
        benchmark::DoNotOptimize(metrics);
    }
    state.SetItemsProcessed(10'000 * state.iterations());
}
BENCHMARK(BM_simulation_10k_bars)->Unit(benchmark::kMillisecond);

static void BM_simulation_100k_bars(benchmark::State& state) {
    auto bars = synthetic_bars(100'000);

    for (auto _ : state) {
        SimulationConfig config{
            .initial_capital = 100'000.0,
            .symbols = {"SYNTH"}
        };

        MarketDataStore store;
        store.load_bars("SYNTH", bars);

        SimulationEngine engine(config);
        engine.load_data(std::move(store));

        auto metrics = engine.run();
        benchmark::DoNotOptimize(metrics);
    }
    state.SetItemsProcessed(100'000 * state.iterations());
}
BENCHMARK(BM_simulation_100k_bars)->Unit(benchmark::kMillisecond);

BENCHMARK_MAIN();
