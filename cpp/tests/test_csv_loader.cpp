#include <doctest/doctest.h>
#include "quant_forge/engine.hpp"
#include <fstream>
#include <cstdio>

using namespace qf;

// Helper: write a small CSV to a temp file, return path
static std::string write_temp_csv(const std::string& content) {
    std::string path = "/tmp/qf_test_bars.csv";
    std::ofstream f(path);
    f << content;
    f.close();
    return path;
}

TEST_CASE("CSV loader: valid file with 2 symbols") {
    std::string csv =
        "symbol,timestamp,open,high,low,close,volume\n"
        "AAPL,2024-01-02,185.0,186.5,184.0,186.0,50000000\n"
        "AAPL,2024-01-03,186.0,188.0,185.5,187.5,52000000\n"
        "AAPL,2024-01-04,187.5,189.0,186.0,188.0,48000000\n"
        "MSFT,2024-01-02,370.0,375.0,368.0,374.0,25000000\n"
        "MSFT,2024-01-03,374.0,378.0,372.0,377.5,23000000\n";
    auto path = write_temp_csv(csv);

    auto data = parse_bars_csv(path);

    CHECK(data.size() == 2);
    CHECK(data.contains("AAPL"));
    CHECK(data.contains("MSFT"));

    // AAPL: 3 bars
    CHECK(data["AAPL"].size() == 3);
    CHECK(data["AAPL"][0].open == doctest::Approx(185.0));
    CHECK(data["AAPL"][0].close == doctest::Approx(186.0));
    CHECK(data["AAPL"][2].volume == 48000000);

    // MSFT: 2 bars
    CHECK(data["MSFT"].size() == 2);
    CHECK(data["MSFT"][1].high == doctest::Approx(378.0));

    // Bars should be sorted by timestamp
    CHECK(data["AAPL"][0].ts < data["AAPL"][1].ts);
    CHECK(data["AAPL"][1].ts < data["AAPL"][2].ts);

    std::remove(path.c_str());
}

TEST_CASE("CSV loader: sorts unsorted input") {
    std::string csv =
        "symbol,timestamp,open,high,low,close,volume\n"
        "SPY,2024-01-04,470.0,472.0,468.0,471.0,80000000\n"
        "SPY,2024-01-02,465.0,468.0,463.0,467.0,75000000\n"
        "SPY,2024-01-03,467.0,471.0,466.0,470.0,78000000\n";
    auto path = write_temp_csv(csv);

    auto data = parse_bars_csv(path);
    CHECK(data["SPY"].size() == 3);

    // Should be sorted by timestamp regardless of input order
    CHECK(data["SPY"][0].open == doctest::Approx(465.0)); // Jan 2
    CHECK(data["SPY"][1].open == doctest::Approx(467.0)); // Jan 3
    CHECK(data["SPY"][2].open == doctest::Approx(470.0)); // Jan 4

    std::remove(path.c_str());
}

TEST_CASE("CSV loader: rejects missing column") {
    std::string csv =
        "symbol,timestamp,open,high,close,volume\n"  // missing 'low'
        "AAPL,2024-01-02,185.0,186.5,186.0,50000000\n";
    auto path = write_temp_csv(csv);

    CHECK_THROWS_AS(parse_bars_csv(path), std::runtime_error);
    std::remove(path.c_str());
}

TEST_CASE("CSV loader: rejects high < low") {
    std::string csv =
        "symbol,timestamp,open,high,low,close,volume\n"
        "AAPL,2024-01-02,185.0,180.0,186.0,184.0,50000000\n";  // high < low
    auto path = write_temp_csv(csv);

    CHECK_THROWS_AS(parse_bars_csv(path), std::runtime_error);
    std::remove(path.c_str());
}

TEST_CASE("CSV loader: rejects negative price") {
    std::string csv =
        "symbol,timestamp,open,high,low,close,volume\n"
        "AAPL,2024-01-02,-185.0,186.5,184.0,186.0,50000000\n";
    auto path = write_temp_csv(csv);

    CHECK_THROWS_AS(parse_bars_csv(path), std::runtime_error);
    std::remove(path.c_str());
}

TEST_CASE("CSV loader: rejects duplicate timestamp per symbol") {
    std::string csv =
        "symbol,timestamp,open,high,low,close,volume\n"
        "AAPL,2024-01-02,185.0,186.5,184.0,186.0,50000000\n"
        "AAPL,2024-01-02,186.0,188.0,185.0,187.0,51000000\n";  // same date
    auto path = write_temp_csv(csv);

    CHECK_THROWS_AS(parse_bars_csv(path), std::runtime_error);
    std::remove(path.c_str());
}

TEST_CASE("CSV loader: rejects invalid date format") {
    std::string csv =
        "symbol,timestamp,open,high,low,close,volume\n"
        "AAPL,01/02/2024,185.0,186.5,184.0,186.0,50000000\n";
    auto path = write_temp_csv(csv);

    CHECK_THROWS_AS(parse_bars_csv(path), std::runtime_error);
    std::remove(path.c_str());
}

TEST_CASE("CSV loader: skips empty lines") {
    std::string csv =
        "symbol,timestamp,open,high,low,close,volume\n"
        "\n"
        "AAPL,2024-01-02,185.0,186.5,184.0,186.0,50000000\n"
        "\n"
        "AAPL,2024-01-03,186.0,188.0,185.5,187.5,52000000\n"
        "   \n";
    auto path = write_temp_csv(csv);

    auto data = parse_bars_csv(path);
    CHECK(data["AAPL"].size() == 2);

    std::remove(path.c_str());
}

TEST_CASE("CSV loader: MarketDataStore.load_csv integrates") {
    std::string csv =
        "symbol,timestamp,open,high,low,close,volume\n"
        "SPY,2024-01-02,465.0,468.0,463.0,467.0,75000000\n"
        "SPY,2024-01-03,467.0,471.0,466.0,470.0,78000000\n"
        "QQQ,2024-01-02,400.0,405.0,398.0,404.0,30000000\n";
    auto path = write_temp_csv(csv);

    MarketDataStore store;
    store.load_csv("", path);  // load_csv ignores symbol param, loads all from file

    auto symbols = store.symbols();
    CHECK(symbols.size() == 2);

    auto spy_bars = store.bars_for("SPY");
    CHECK(spy_bars.size() == 2);

    auto qqq_bars = store.bars_for("QQQ");
    CHECK(qqq_bars.size() == 1);
    CHECK(qqq_bars[0].close == doctest::Approx(404.0));

    std::remove(path.c_str());
}
