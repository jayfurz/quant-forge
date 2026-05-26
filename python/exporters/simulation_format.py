"""
Export cleaned data to formats consumable by the C++ simulation engine.
Output: CSV (default) or Parquet with standardized schema.
"""

import logging
from pathlib import Path
from typing import Optional

import polars as pl

logger = logging.getLogger(__name__)

# Schema that matches C++ types.hpp Bar struct
QUANT_FORGE_SCHEMA = {
    "ts":     pl.Utf8,    # ISO-8601 timestamp (C++ parses as nanosecond epoch)
    "open":   pl.Float64,
    "high":   pl.Float64,
    "low":    pl.Float64,
    "close":  pl.Float64,
    "volume": pl.Int64,
}


def to_simulation_format(df: pl.DataFrame, symbol: str) -> pl.DataFrame:
    """
    Convert a DataFrame to the standard simulation format.
    Columns: ts, open, high, low, close, volume, symbol
    """
    out = df.select([
        pl.col("ts").cast(pl.Utf8),
        pl.col("open"),
        pl.col("high"),
        pl.col("low"),
        pl.col("close"),
        pl.col("volume").cast(pl.Int64),
    ]).with_columns(pl.lit(symbol).alias("symbol"))

    return out


def export_csv(df: pl.DataFrame, path: Path | str) -> None:
    """Export to CSV with QuantForge schema."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.write_csv(p)
    logger.info("Exported %d rows to %s", df.height, p)


def export_parquet(df: pl.DataFrame, path: Path | str) -> None:
    """Export to Parquet (faster to load, preserves types)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(p, compression="zstd")
    logger.info("Exported %d rows to %s", df.height, p)


def prepare_universe(
    raw_dir: str = "data/market_data",
    clean_dir: str = "data/clean",
    symbols: Optional[list[str]] = None
) -> list[Path]:
    """
    Process all CSVs in raw_dir → clean standardized format.
    Returns list of output paths.
    """
    raw = Path(raw_dir)
    clean = Path(clean_dir)
    clean.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(raw.glob("*.csv"))
    output_paths = []

    for csv_path in csv_files:
        symbol = csv_path.stem.split("_")[0]  # Parse symbol from filename

        if symbols and symbol not in symbols:
            continue

        try:
            df = pl.read_csv(csv_path, try_parse_dates=True)
            df = to_simulation_format(df, symbol)
            out_path = clean / f"{symbol}.parquet"
            export_parquet(df, out_path)
            output_paths.append(out_path)
        except Exception as e:
            logger.error("Failed to process %s: %s", csv_path, e)

    return output_paths


def generate_universe_config(
    symbols: list[str],
    start_date: str,
    end_date: str,
    output_path: str = "configs/universe.json"
) -> None:
    """
    Generate a universe config file for the C++ backtester.
    """
    import json

    config = {
        "symbols": symbols,
        "start_date": start_date,
        "end_date": end_date,
        "data_dir": "../data/clean",
        "initial_capital": 100_000.0,
        "commission_per_share": 0.005,
        "bar_size": "1d",
    }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(config, indent=2))
    logger.info("Universe config written: %d symbols → %s", len(symbols), output_path)
