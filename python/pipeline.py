#!/usr/bin/env python3
"""
QuantForge — Defense / AI Infrastructure Signal Tracker

End-to-end pipeline:
  1. Download market data (Yahoo OHLCV)
  2. Pull SEC filings → filing diff scores
  3. Pull federal contracts → award velocity
  4. Pull job postings → AI hiring acceleration
  5. Combine → composite signal
  6. Export for C++ backtester

Usage:
  python pipeline.py --symbols LMT,RTX,NOC --start 2023-01-01 --end 2025-12-31
"""

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

import polars as pl

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("quantforge")


def run_pipeline(
    symbols: list[str],
    start_date: str,
    end_date: str,
    use_cached: bool = False
):
    """Run full defense signal pipeline."""

    # ── Step 1: Market Data ──────────────────────────────────────
    logger.info("STEP 1: Downloading OHLCV for %d symbols", len(symbols))
    from downloaders.ohlcv import download_batch
    price_data = download_batch(
        symbols, start_date, end_date,
        output_dir="data/market_data",
        delay_s=0.5
    )
    logger.info("Downloaded %d/%d symbols", len(price_data), len(symbols))

    # ── Step 2: SEC Filing Analysis ──────────────────────────────
    logger.info("STEP 2: SEC filing analysis")
    from downloaders.sec_edgar import ticker_to_cik, fetch_company_facts, fetch_filing_history

    filing_scores = {}
    for sym in symbols:
        try:
            cik = ticker_to_cik(sym)
            if not cik:
                logger.warning("No CIK found for %s", sym)
                continue

            facts = fetch_company_facts(cik)
            metrics = facts.get("facts", {}).get("us-gaap", {})

            # Extract revenue trend
            rev_data = metrics.get("Revenues", {}).get("units", {}).get("USD", [])
            if rev_data:
                rev_sorted = sorted(rev_data, key=lambda x: x.get("filed", ""), reverse=True)
                recent = rev_sorted[:4]  # Last 4 quarters
                filing_scores[sym] = {
                    "quarters_filed": len(recent),
                    "latest_revenue": recent[0].get("val") if recent else None,
                    "cik": cik,
                }
                logger.info("  %s: %d quarters filed", sym, len(recent))
        except Exception as e:
            logger.error("  %s SEC analysis failed: %s", sym, e)

    # ── Step 3: Defense Contract Awards ──────────────────────────
    logger.info("STEP 3: Defense contract awards")
    from downloaders.gov_contracts import fetch_defense_contracts_by_vendor, contract_award_velocity

    # Map tickers to vendor names for defense contractors
    DEFENSE_VENDORS = {
        "LMT": "Lockheed Martin",
        "RTX": "Raytheon Technologies",
        "NOC": "Northrop Grumman",
        "GD":  "General Dynamics",
        "BA":  "Boeing",
        "LHX": "L3Harris",
        "HII": "Huntington Ingalls",
    }

    vendor_names = [DEFENSE_VENDORS.get(s, s) for s in symbols if s in DEFENSE_VENDORS]
    contract_data = pl.DataFrame()

    if vendor_names:
        try:
            contract_data = fetch_defense_contracts_by_vendor(vendor_names, start_date, end_date)
            if not contract_data.is_empty():
                velocity = contract_award_velocity(contract_data)
                logger.info("  Contracts found: %d awards across %s",
                           contract_data.height, ", ".join(vendor_names))
        except Exception as e:
            logger.error("  Contract fetch failed: %s", e)

    # ── Step 4: AI Hiring Signal ─────────────────────────────────
    logger.info("STEP 4: AI/Defense hiring signal")
    from downloaders.job_postings import fetch_usajobs, build_hiring_signal

    AI_DEFENSE_KEYWORDS = [
        "artificial intelligence", "machine learning", "CUDA", "GPU",
        "missile", "radar", "aerospace", "C++", "embedded",
        "cybersecurity", "top secret", "weapon systems",
    ]

    jobs_data = pl.DataFrame()
    try:
        jobs_data = fetch_usajobs(AI_DEFENSE_KEYWORDS)
        if not jobs_data.is_empty():
            hiring_signal = build_hiring_signal(jobs_data)
            logger.info("  Jobs found: %d postings across %d keywords",
                       jobs_data.height, len(AI_DEFENSE_KEYWORDS))
    except Exception as e:
        logger.error("  Job fetching failed: %s", e)

    # ── Step 5: Composite Signal ─────────────────────────────────
    logger.info("STEP 5: Building composite signal")
    from features.signal_builder import build_composite_signal

    signals = {}
    for sym in symbols:
        sym_price = price_data.get(sym)
        signals[sym] = build_composite_signal(
            symbol=sym,
            sec_filing_score=filing_scores.get(sym),
            hiring_score=jobs_data if not jobs_data.is_empty() else None,
            contract_score=contract_data if not contract_data.is_empty() else None,
            price_data=sym_price,
        )
        logger.info("  %s: composite=%.2f → %s",
                   sym,
                   signals[sym]["composite_score"],
                   signals[sym]["interpretation"])

    # ── Step 6: Export ───────────────────────────────────────────
    logger.info("STEP 6: Exporting signals")
    from exporters.simulation_format import prepare_universe, generate_universe_config

    prepare_universe(symbols=symbols)
    generate_universe_config(symbols, start_date, end_date)

    # Save signals JSON
    signals_path = Path("data/signals.json")
    signals_path.parent.mkdir(parents=True, exist_ok=True)
    signals_path.write_text(json.dumps(signals, indent=2, default=str))
    logger.info("Signals saved to %s", signals_path)

    # ── Summary ──────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("QUANTFORGE SIGNAL REPORT")
    print("=" * 60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Symbols: {', '.join(symbols)}")
    print()

    for sym, signal in signals.items():
        emoji = {"STRONG_BULLISH": "🟢🟢", "BULLISH": "🟢", "NEUTRAL": "⚪",
                 "BEARISH": "🔴", "STRONG_BEARISH": "🔴🔴"}.get(signal["interpretation"], "⚪")
        print(f"{emoji} {sym:5s}  {signal['composite_score']:+6.2f}  {signal['interpretation']}")

    print("\nComponents:")
    for comp_name in ["filing_risk", "ai_hiring", "contract_awards", "evasiveness", "price_momentum"]:
        if any(comp_name in s.get("components", {}) for s in signals.values()):
            vals = [s.get("components", {}).get(comp_name, 0) for s in signals.values()]
            avg = sum(vals) / len(vals) if vals else 0
            print(f"  {comp_name:20s}: {'🟢' if avg > 0 else '🔴'} {avg:+.2f}")

    print("=" * 60)

    return signals


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QuantForge Signal Pipeline")
    parser.add_argument("--symbols", default="LMT,RTX,NOC,GD,BA",
                       help="Comma-separated tickers")
    parser.add_argument("--start", default="2023-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default="2025-12-31", help="End date YYYY-MM-DD")
    parser.add_argument("--cached", action="store_true", help="Use cached data")
    parser.add_argument("--export-only", action="store_true", help="Only export, no download")

    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",")]

    run_pipeline(symbols, args.start, args.end, args.cached)
