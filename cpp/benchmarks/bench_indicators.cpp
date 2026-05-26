#include <benchmark/benchmark.h>
#include "quant_forge/indicators.hpp"
#include <vector>
#include <random>

using namespace qf::indicators;

static constexpr size_t N = 1'000'000;

static void BM_sma_vectorized(benchmark::State& state) {
    std::vector<double> prices(N);
    std::mt19937 rng(42);
    std::normal_distribution<double> dist(100.0, 10.0);
    for (auto& p : prices) p = dist(rng);

    std::vector<double> out(N);
    for (auto _ : state) {
        sma_vectorized(prices.data(), out.data(), N, 20);
        benchmark::DoNotOptimize(out);
    }
    state.SetItemsProcessed(N * state.iterations());
}
BENCHMARK(BM_sma_vectorized)->Unit(benchmark::kMillisecond);

static void BM_ema_vectorized(benchmark::State& state) {
    std::vector<double> prices(N);
    std::mt19937 rng(42);
    std::normal_distribution<double> dist(100.0, 10.0);
    for (auto& p : prices) p = dist(rng);

    std::vector<double> out(N);
    for (auto _ : state) {
        ema_vectorized(prices.data(), out.data(), N, 20);
        benchmark::DoNotOptimize(out);
    }
    state.SetItemsProcessed(N * state.iterations());
}
BENCHMARK(BM_ema_vectorized)->Unit(benchmark::kMillisecond);

static void BM_rsi_incremental(benchmark::State& state) {
    std::vector<double> prices(N);
    std::mt19937 rng(42);
    std::normal_distribution<double> dist(100.0, 1.0);
    for (auto& p : prices) p = dist(rng);

    for (auto _ : state) {
        RSI rsi{14};
        for (size_t i = 1; i < prices.size(); ++i) {
            rsi.push(prices[i], prices[i - 1]);
            benchmark::DoNotOptimize(rsi.current());
        }
    }
    state.SetItemsProcessed(N * state.iterations());
}
BENCHMARK(BM_rsi_incremental)->Unit(benchmark::kMillisecond);

BENCHMARK_MAIN();
