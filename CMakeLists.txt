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
    src/engine/engine.cpp
    src/engine/data_loader.cpp
    src/indicators/indicators.cpp
    src/orders/fill_model.cpp
    src/metrics/metrics.cpp
)
target_include_directories(quant_forge_core PUBLIC include)
target_link_libraries(quant_forge_core PUBLIC fmt::fmt nlohmann_json::nlohmann_json SQLite::SQLite3)
if(DuckDB_FOUND)
    target_link_libraries(quant_forge_core PUBLIC DuckDB::DuckDB)
    target_compile_definitions(quant_forge_core PUBLIC HAS_DUCKDB)
endif()

# ── CLI / Runner ──────────────────────────────────────────────────
add_executable(qf-runner src/main.cpp)
target_link_libraries(qf-runner PRIVATE quant_forge_core)

# ── Tests ─────────────────────────────────────────────────────────
enable_testing()
find_package(doctest QUIET)
if(doctest_FOUND)
    add_executable(qf-tests
        tests/test_main.cpp
        tests/test_indicators.cpp
        tests/test_portfolio.cpp
        tests/test_order_fill.cpp
        tests/test_metrics.cpp
    )
    target_link_libraries(qf-tests PRIVATE quant_forge_core doctest::doctest)
    add_test(NAME qf-tests COMMAND qf-tests)
endif()

# ── Benchmarks ────────────────────────────────────────────────────
find_package(benchmark QUIET)
if(benchmark_FOUND)
    add_executable(qf-benchmarks
        benchmarks/bench_indicators.cpp
        benchmarks/bench_engine.cpp
    )
    target_link_libraries(qf-benchmarks PRIVATE quant_forge_core benchmark::benchmark)
endif()
