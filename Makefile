.PHONY: all build test bench clean python-setup data

# ── C++ ───────────────────────────────────────────────────────────
BUILD_DIR := build
CMAKE_FLAGS := -DCMAKE_BUILD_TYPE=Release

all: build

build:
	@mkdir -p $(BUILD_DIR)
	cd $(BUILD_DIR) && cmake .. $(CMAKE_FLAGS) && make -j$(shell nproc)

test: build
	cd $(BUILD_DIR) && ctest --output-on-failure

bench: build
	cd $(BUILD_DIR) && ./qf-benchmarks

clean:
	rm -rf $(BUILD_DIR)

# ── Python ────────────────────────────────────────────────────────
python-setup:
	python -m venv .venv
	.venv/bin/pip install -e ".[dev]"

lint:
	.venv/bin/ruff check python/
	.venv/bin/mypy python/

# ── Data ──────────────────────────────────────────────────────────
data-sp500:
	.venv/bin/python -c "
from downloaders.ohlcv import fetch_sp500_symbols, download_batch
symbols = fetch_sp500_symbols()
print(f'Downloading {len(symbols)} symbols...')
download_batch(symbols, '2023-01-01', '2025-12-31', output_dir='data/market_data')
"

data-prepare:
	.venv/bin/python -c "
from exporters.simulation_format import prepare_universe
paths = prepare_universe()
print(f'Prepared {len(paths)} files')
"

# ── Full Pipeline ─────────────────────────────────────────────────
pipeline: data-prepare build
	cd $(BUILD_DIR) && ./qf-runner --config ../configs/universe.json
