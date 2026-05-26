cmake_minimum_required(VERSION 3.20)
project(quant-forge VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(CMAKE_BUILD_TYPE STREQUAL "Release")
    add_compile_options(-O3 -march=native -flto)
endif()
add_compile_options(-Wall -Wextra -Wpedantic)

# ── Dependencies ──────────────────────────────────────────────────
find_package(fmt REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(SQLite3 REQUIRED)

# Optionally find DuckDB, fallback to SQLite
find_package(DuckDB QUIET)

# ── Core Library (consolidated sources) ──────────────────────────
add_library(quant_forge_core STATIC
    cpp/src/engine/engine.cpp
    cpp/src/engine/data_loader.cpp
    cpp/src/indicators/indicators.cpp
    cpp/src/orders/fill_model.cpp
    cpp/src/metrics/metrics.cpp
    cpp/src/strategies/momentum_ema_hysteresis.cpp
)
target_include_directories(quant_forge_core PUBLIC cpp/include)
target_link_libraries(quant_forge_core PUBLIC fmt::fmt nlohmann_json::nlohmann_json SQLite3::SQLite3)
if(DuckDB_FOUND)
    target_link_libraries(quant_forge_core PUBLIC DuckDB::DuckDB)
    target_compile_definitions(quant_forge_core PUBLIC HAS_DUCKDB)
endif()

# ── CLI / Runner ──────────────────────────────────────────────────
add_executable(qf-runner cpp/src/main.cpp)
target_link_libraries(qf-runner PRIVATE quant_forge_core)

# ── Vendored doctest ──────────────────────────────────────────────
add_library(doctest INTERFACE)
target_include_directories(doctest INTERFACE extern)

# ── Tests ─────────────────────────────────────────────────────────
enable_testing()
add_executable(qf-tests
    cpp/tests/test_main.cpp
    cpp/tests/test_indicators.cpp
    cpp/tests/test_portfolio.cpp
    cpp/tests/test_order_fill.cpp
    cpp/tests/test_metrics.cpp
    cpp/tests/test_csv_loader.cpp
)
target_link_libraries(qf-tests PRIVATE quant_forge_core doctest)
add_test(NAME qf-tests COMMAND qf-tests)

# ── Benchmarks ────────────────────────────────────────────────────
find_package(benchmark QUIET)
if(benchmark_FOUND)
    add_executable(qf-benchmarks
        cpp/benchmarks/bench_indicators.cpp
        cpp/benchmarks/bench_engine.cpp
    )
    target_link_libraries(qf-benchmarks PRIVATE quant_forge_core benchmark::benchmark)
endif()
