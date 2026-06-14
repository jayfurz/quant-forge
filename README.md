# QuantForge

C++ backtesting engine + Python data pipeline for quantitative strategy research.

## Architecture

```
python/          → Data Pipeline (download, clean, export)
  downloaders/     Yahoo Finance, SEC EDGAR, FRED, FINRA
  cleaners/        Missing values, splits, outliers, calendar alignment
  exporters/       CSV/Parquet in simulation-ready format
cpp/             → Simulation Engine (C++23)
  src/engine/      Event-driven backtester, data loader
  src/indicators/  SMA, EMA, RSI, MACD, Bollinger Bands, ATR
  src/portfolio/   Multi-asset portfolio with margin tracking
  src/orders/      Order management, fill simulation, slippage
  src/metrics/     Sharpe, Sortino, drawdown, win rate, profit factor
data/            → Raw + cleaned market data
  raw/             Downloaded CSVs
  clean/           Parquet files (simulation-ready)
  market_data/     Yahoo Finance downloads
configs/         → JSON universe configs for the C++ runner
research/        → Jupyter notebooks for strategy exploration
```

## Quick Start

### 1. Download data
```bash
cd python
python -c "
from downloaders.ohlcv import download_batch
download_batch(['AAPL', 'MSFT', 'GOOGL'], '2020-01-01', '2025-12-31')
"
```

### 2. Clean and export
```bash
python -c "
from cleaners.ohlcv_cleaner import clean_ohlcv
from exporters.simulation_format import prepare_universe
prepare_universe()
"
```

### 3. Build and run the C++ engine
```bash
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
./qf-runner --config ../configs/universe.json
```

## Data Sources

| Source | Data | Auth |
|--------|------|------|
| Yahoo Finance | Daily OHLCV | None |
| SEC EDGAR | Company filings, financials, Form 4 | None (10 req/s limit) |
| FRED | Economic indicators (CPI, rates) | Free API key |
| FINRA | Short interest, trade data | None |

## Strategy Interface

```cpp
struct Strategy {
    std::string id;
    StrategyFunc generate_signals;  // bars → signals
    BarSize bar_size;
    std::vector<std::string> symbols;
};
```

## Metrics Output

- Total return %, annualized return %
- Sharpe ratio, Sortino ratio, Calmar ratio
- Max drawdown %, daily volatility %
- Win rate %, profit factor, average trade P&L
- Equity curve (timestamped for plotting)

## Status

- [x] Project scaffold
- [x] Python data pipeline (Yahoo + SEC + USAspending)
- [x] PIT research stack (FeatureStore, PIT joiner, forward returns, study runner)
- [x] C++ types + indicators
- [x] C++ simulation engine implementation
- [x] C++ metrics implementation (round-trip P&L based)
- [x] Order/fill model implementation
- [x] Portfolio + P&L tracker
- [x] CLI runner (`qf-runner`)
- [x] Test suite (C++ `qf-tests`, Python `pytest python/tests`)
- [ ] Benchmark suite (needs `benchmark` package)

See `reports/contract_award_velocity/RESEARCH_NOTES.md` for the research
write-up and the v1→v2 bug-fix / rearchitecture log.

## Build & Test

```bash
# C++ (zero external deps)
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j
./build/qf-tests

# Python
pip install -e .            # or: pip install polars requests pyarrow numpy pytest
python -m pytest python/tests -q
```
