#include <doctest/doctest.h>
#include <vector>
#include <span>

// Manual test stubs until doctest is available
#include "quant_forge/indicators.hpp"

using namespace qf::indicators;

TEST_CASE("SMA basic") {
    SMA sma{3};
    CHECK(!sma.current().has_value());

    sma.push(10.0);
    sma.push(20.0);
    CHECK(!sma.current().has_value());

    sma.push(30.0);
    auto val = sma.current();
    CHECK(val.has_value());
    CHECK(val.value() == doctest::Approx(20.0));
}

TEST_CASE("SMA rolling") {
    SMA sma{3};
    sma.push(10.0);
    sma.push(20.0);
    sma.push(30.0);
    sma.push(40.0);  // drops 10, window: [20, 30, 40]

    auto val = sma.current();
    CHECK(val.has_value());
    CHECK(val.value() == doctest::Approx(30.0));
}

TEST_CASE("EMA basic") {
    EMA ema{3};  // alpha = 2/(3+1) = 0.5
    ema.push(10.0);
    CHECK(ema.current().value() == doctest::Approx(10.0));

    ema.push(20.0);  // 0.5*20 + 0.5*10 = 15
    CHECK(ema.current().value() == doctest::Approx(15.0));

    ema.push(30.0);  // 0.5*30 + 0.5*15 = 22.5
    CHECK(ema.current().value() == doctest::Approx(22.5));
}

TEST_CASE("RSI basic") {
    RSI rsi{4};
    rsi.push(102.0, 100.0);  // +2
    rsi.push(105.0, 102.0);  // +3
    rsi.push(103.0, 105.0);  // -2
    rsi.push(108.0, 103.0);  // +5

    auto val = rsi.current();
    CHECK(val.has_value());
    // avg_gain = (2+3+0+5)/4 = 2.5, avg_loss = (0+0+2+0)/4 = 0.5
    // rs = 5.0, rsi = 100 - 100/(1+5) = 83.33
    CHECK(val.value() == doctest::Approx(83.33).epsilon(0.01));
}

TEST_CASE("Bollinger Bands") {
    BollingerBands bb{3, 2.0};
    bb.push(10.0);
    bb.push(12.0);
    bb.push(14.0);

    auto res = bb.current();
    CHECK(res.has_value());
    CHECK(res->middle == doctest::Approx(12.0));
    CHECK(res->upper > res->middle);
    CHECK(res->lower < res->middle);
}

TEST_CASE("MACD") {
    MACD macd{3, 6, 3};
    for (int i = 0; i < 30; ++i) macd.push(100.0 + i * 0.5);

    // Should converge to valid values after warmup
    CHECK(macd.current().has_value());
}

TEST_CASE("SMA vectorized") {
    double prices[] = {10, 20, 30, 40, 50};
    double out[5];
    sma_vectorized(prices, out, 5, 3);

    CHECK(out[0] == doctest::Approx(0.0));
    CHECK(out[1] == doctest::Approx(0.0));
    CHECK(out[2] == doctest::Approx(20.0));  // avg(10,20,30)
    CHECK(out[3] == doctest::Approx(30.0));  // avg(20,30,40)
    CHECK(out[4] == doctest::Approx(40.0));  // avg(30,40,50)
}

TEST_CASE("EMA vectorized") {
    double prices[] = {10, 20, 30, 40};
    double out[4];
    ema_vectorized(prices, out, 4, 3);

    CHECK(out[0] == doctest::Approx(10.0));
    // alpha = 0.5
    // out[1] = 0.5*20 + 0.5*10 = 15
    // out[2] = 0.5*30 + 0.5*15 = 22.5
    // out[3] = 0.5*40 + 0.5*22.5 = 31.25
    CHECK(out[1] == doctest::Approx(15.0));
    CHECK(out[2] == doctest::Approx(22.5));
    CHECK(out[3] == doctest::Approx(31.25));
}
