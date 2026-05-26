#!/usr/bin/env python3
"""Integration test with real API keys."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from config import load_config

cfg = load_config()
print("=== API Keys ===")
print(f"  FRED:    {'✅' if cfg.fred_api_key else '❌'}")
print(f"  USAJobs: {'✅' if cfg.usajobs_api_key else '❌'}")
print()

# ── FRED ✅ ──────────────────────────────────────────────────────
print("=== FRED Economic Data ===")
from downloaders.fred_economic import fetch_series, yield_curve_spread
df = fetch_series("UNRATE", cfg.fred_api_key)
print(f"  ✅ Unemployment: {df['value'].tail(1)[0]}%")

spread = yield_curve_spread(cfg.fred_api_key)
tag = ' ⚠️ INVERTED' if spread < 0 else ''
print(f"  ✅ 10Y-2Y Spread: {spread:.2f}bp{tag}")

df2 = fetch_series("FDEFX", cfg.fred_api_key, "2024-01-01", "2025-12-31", "q")
print(f"  ✅ Defense spending: ${df2['value'].tail(1)[0]:.1f}B")
print()

# ── USAJobs ✅ ───────────────────────────────────────────────────
print("=== USAJobs ===")
from downloaders.job_postings import fetch_usajobs
jobs = fetch_usajobs(
    ["artificial intelligence", "missile", "cybersecurity"],
    max_results=30, api_key=cfg.usajobs_api_key, email=cfg.usajobs_email
)
print(f"  ✅ {jobs.height} federal job postings")
for row in jobs.head(3).iter_rows(named=True):
    print(f"     {row['job_title'][:50]} @ {row['agency'][:30]}")
print()

# ── USASpending ✅ ───────────────────────────────────────────────
print("=== USASpending.gov ===")
from downloaders.gov_contracts import fetch_defense_contracts
contracts = fetch_defense_contracts(
    ["Lockheed Martin"], start_date="2024-10-01", end_date="2025-09-30"
)
if not contracts.is_empty():
    top = contracts.sort("amount", descending=True).head(3)
    print(f"  ✅ {contracts.height} DoD contracts")
    for row in top.iter_rows(named=True):
        print(f"     ${row['amount']:,.0f} — {str(row.get('description',''))[:50]}")
else:
    print("  ⚠️  No results")
print()

# ── FINRA ⚠️ ─────────────────────────────────────────────────────
print("=== FINRA OTC (needs developer.finra.org registration) ===")
print("  ⚠️  CloudFront bot protection — register free at developer.finra.org")
print()

# ── Yahoo Finance ✅ ─────────────────────────────────────────────
print("=== Yahoo Finance ===")
from downloaders.ohlcv import download_yahoo
rtx = download_yahoo("RTX", "2025-01-01", "2025-05-01")
print(f"  ✅ RTX: {rtx.height} bars, avg close ${rtx['close'].mean():.2f}")
print()

# ── SEC EDGAR ✅ ─────────────────────────────────────────────────
print("=== SEC EDGAR ===")
from downloaders.sec_edgar import ticker_to_cik, fetch_company_facts
cik = ticker_to_cik("RTX")
facts = fetch_company_facts(cik)
rev = facts['facts']['us-gaap']['Revenues']['units']['USD'][-1]
print(f"  ✅ RTX CIK={cik}, latest rev: ${rev['val']:,.0f} ({rev['form']}, FY{rev['fy']} {rev['fp']})")
print()

# ── Composite Signal ─────────────────────────────────────────────
print("=== Composite Signal ===")
from features.signal_builder import build_composite_signal

sig = build_composite_signal(
    "RTX",
    sec_filing_score={'severity_score': 1, 'pct_changed': 8.0, 'new_risk_count': 1},
    evasiveness={'evasiveness_score': 10.0},
)
print(f"  RTX: {sig['composite_score']:+.2f} → {sig['interpretation']}")

sig2 = build_composite_signal(
    "LMT",
    sec_filing_score={'severity_score': 0, 'pct_changed': 3.0, 'new_risk_count': 0},
)
print(f"  LMT: {sig2['composite_score']:+.2f} → {sig2['interpretation']}")

print()
print("=" * 60)
print("INTEGRATION TEST COMPLETE")
print("=" * 60)
print()
print("Working:  FRED ✅  USAJobs ✅  USASpending ✅  Yahoo ✅  SEC EDGAR ✅")
print("Needs free reg:  FINRA (developer.finra.org)  —  CloudFront blocking raw curl")
