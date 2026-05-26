#include "quant_forge/engine.hpp"
#include <fstream>
#include <sstream>
#include <unordered_map>
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <charconv>

namespace qf {

namespace {

constexpr Timestamp SECONDS_PER_DAY = 86'400;
constexpr Timestamp NANOS_PER_SECOND = 1'000'000'000;
constexpr Timestamp NANOS_PER_DAY = SECONDS_PER_DAY * NANOS_PER_SECOND;

// Parse "YYYY-MM-DD" → nanosecond epoch
// Uses POSIX days since 1970-01-01 (matches typical CSV date conventions)
Timestamp parse_date(std::string_view sv) {
    if (sv.size() != 10 || sv[4] != '-' || sv[7] != '-') {
        throw std::runtime_error("Invalid date format: " + std::string(sv) + " (expected YYYY-MM-DD)");
    }

    int year = 0, month = 0, day = 0;
    auto [ptr_y, ec_y] = std::from_chars(sv.data(), sv.data() + 4, year);
    auto [ptr_m, ec_m] = std::from_chars(sv.data() + 5, sv.data() + 7, month);
    auto [ptr_d, ec_d] = std::from_chars(sv.data() + 8, sv.data() + 10, day);

    if (ec_y != std::errc{} || ec_m != std::errc{} || ec_d != std::errc{}) {
        throw std::runtime_error("Invalid date: " + std::string(sv));
    }

    // Days since 1970-01-01 (simplified — good for 1970–2099)
    // Algorithm from http://howardhinnant.github.io/date_algorithms.html
    year -= (month <= 2) ? 1 : 0;
    int era = (year >= 0 ? year : year - 399) / 400;
    int yoe = static_cast<int>(year - era * 400);
    int doy = (153 * (month + (month > 2 ? -3 : 9)) + 2) / 5 + day - 1;
    int doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    int64_t days_since_epoch = era * 146097 + doe - 719468;

    return days_since_epoch * NANOS_PER_DAY;
}

double parse_double(std::string_view sv) {
    // Use std::from_chars for fast float parsing
    double val = 0.0;
    auto [ptr, ec] = std::from_chars(sv.data(), sv.data() + sv.size(), val);
    if (ec != std::errc{}) {
        throw std::runtime_error("Invalid numeric value: " + std::string(sv));
    }
    return val;
}

int64_t parse_int64(std::string_view sv) {
    int64_t val = 0;
    auto [ptr, ec] = std::from_chars(sv.data(), sv.data() + sv.size(), val);
    if (ec != std::errc{}) {
        throw std::runtime_error("Invalid integer value: " + std::string(sv));
    }
    return val;
}

// Split a line by comma, respecting no quoting (simple CSV)
std::vector<std::string_view> split_csv_line(std::string_view line) {
    std::vector<std::string_view> fields;
    size_t start = 0;
    while (start <= line.size()) {
        size_t end = line.find(',', start);
        if (end == std::string_view::npos) {
            fields.push_back(line.substr(start));
            break;
        }
        fields.push_back(line.substr(start, end - start));
        start = end + 1;
    }
    return fields;
}

} // anonymous namespace

std::unordered_map<std::string, std::vector<Bar>> parse_bars_csv(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) {
        throw std::runtime_error("Cannot open CSV file: " + path);
    }

    std::unordered_map<std::string, std::vector<Bar>> result;

    std::string line;
    size_t line_num = 0;

    // Read header
    if (!std::getline(file, line)) {
        throw std::runtime_error("Empty CSV file: " + path);
    }
    line_num++;

    auto header = split_csv_line(line);
    // Expected: symbol,timestamp,open,high,low,close,volume
    if (header.size() != 7) {
        throw std::runtime_error(
            "CSV header has " + std::to_string(header.size()) +
            " columns, expected 7 (symbol,timestamp,open,high,low,close,volume)");
    }

    // Find column indices
    int idx_symbol = -1, idx_ts = -1, idx_open = -1, idx_high = -1;
    int idx_low = -1, idx_close = -1, idx_volume = -1;

    for (size_t i = 0; i < header.size(); ++i) {
        std::string h(header[i]);
        // Trim whitespace
        h.erase(0, h.find_first_not_of(" \t\r\n"));
        h.erase(h.find_last_not_of(" \t\r\n") + 1);

        if (h == "symbol") idx_symbol = static_cast<int>(i);
        else if (h == "timestamp") idx_ts = static_cast<int>(i);
        else if (h == "open") idx_open = static_cast<int>(i);
        else if (h == "high") idx_high = static_cast<int>(i);
        else if (h == "low") idx_low = static_cast<int>(i);
        else if (h == "close") idx_close = static_cast<int>(i);
        else if (h == "volume") idx_volume = static_cast<int>(i);
    }

    // Validate all required columns present
    auto check_col = [&](int idx, const char* name) {
        if (idx < 0) {
            throw std::runtime_error(
                std::string("CSV missing required column '") + name + "' in " + path);
        }
    };
    check_col(idx_symbol, "symbol");
    check_col(idx_ts, "timestamp");
    check_col(idx_open, "open");
    check_col(idx_high, "high");
    check_col(idx_low, "low");
    check_col(idx_close, "close");
    check_col(idx_volume, "volume");

    // Parse data rows
    while (std::getline(file, line)) {
        line_num++;

        // Skip empty lines
        if (line.empty() || line.find_first_not_of(" \t\r\n") == std::string::npos) {
            continue;
        }

        auto fields = split_csv_line(line);
        if (fields.size() < 7) {
            throw std::runtime_error(
                "CSV line " + std::to_string(line_num) + " has " +
                std::to_string(fields.size()) + " fields, expected 7");
        }

        Bar bar{};
        std::string symbol(fields[idx_symbol]);

        // Trim symbol
        symbol.erase(0, symbol.find_first_not_of(" \t\r\n"));
        symbol.erase(symbol.find_last_not_of(" \t\r\n") + 1);

        bar.ts     = parse_date(fields[idx_ts]);
        bar.open   = parse_double(fields[idx_open]);
        bar.high   = parse_double(fields[idx_high]);
        bar.low    = parse_double(fields[idx_low]);
        bar.close  = parse_double(fields[idx_close]);
        bar.volume = parse_int64(fields[idx_volume]);

        // ── Validation ──────────────────────────────────────────────
        // OHLC values must be non-negative
        if (bar.open < 0 || bar.high < 0 || bar.low < 0 || bar.close < 0) {
            throw std::runtime_error(
                "Negative OHLC value at line " + std::to_string(line_num) +
                " in " + path);
        }

        // high >= low
        if (bar.high < bar.low) {
            throw std::runtime_error(
                "high < low at line " + std::to_string(line_num) +
                " (high=" + std::to_string(bar.high) +
                ", low=" + std::to_string(bar.low) + ")");
        }

        // high >= open, high >= close
        if (bar.high < bar.open) {
            throw std::runtime_error(
                "high < open at line " + std::to_string(line_num));
        }
        if (bar.high < bar.close) {
            throw std::runtime_error(
                "high < close at line " + std::to_string(line_num));
        }

        // low <= open, low <= close
        if (bar.low > bar.open) {
            throw std::runtime_error(
                "low > open at line " + std::to_string(line_num));
        }
        if (bar.low > bar.close) {
            throw std::runtime_error(
                "low > close at line " + std::to_string(line_num));
        }

        // volume >= 0
        if (bar.volume < 0) {
            throw std::runtime_error(
                "Negative volume at line " + std::to_string(line_num));
        }

        result[symbol].push_back(bar);
    }

    // Per-symbol: check timestamp ordering and duplicates
    for (auto& [symbol, bars] : result) {
        if (bars.empty()) continue;

        std::ranges::sort(bars, [](const Bar& a, const Bar& b) {
            return a.ts < b.ts;
        });

        // Check for duplicate timestamps per symbol
        for (size_t i = 1; i < bars.size(); ++i) {
            if (bars[i].ts == bars[i - 1].ts) {
                throw std::runtime_error(
                    "Duplicate timestamp for symbol '" + symbol +
                    "' at ts=" + std::to_string(bars[i].ts));
            }
        }
    }

    return result;
}

// ── MarketDataStore::load_csv ──────────────────────────────────────
void MarketDataStore::load_csv(const std::string& /*symbol*/, const std::string& path) {
    auto data = parse_bars_csv(path);
    for (auto& [symbol, bars] : data) {
        load_bars(symbol, bars);
    }
}

} // namespace qf
