"""
SEC EDGAR downloader — company filings, financials, insider trades.

Rate limit: 10 req/sec (SEC fair access policy).
No API key required.
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import polars as pl
import requests

logger = logging.getLogger(__name__)

SEC_BASE = "https://data.sec.gov"
HEADERS = {
    "User-Agent": "QuantForge/0.1 (justin0106@protonmail.com)",
    "Accept-Encoding": "gzip, deflate"
}

# ── Company Facts (XBRL) ─────────────────────────────────────────
def fetch_company_facts(cik: str) -> dict:
    """
    Fetch all XBRL-tagged financial facts for a CIK.
    Returns the full companyfacts JSON.
    """
    cik_padded = str(cik).zfill(10)
    url = f"{SEC_BASE}/api/xbrl/companyfacts/CIK{cik_padded}.json"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def extract_key_metrics(cik: str) -> pl.DataFrame:
    """
    Extract key financial metrics from company facts:
    Revenue, Net Income, EPS (basic + diluted), Assets, Liabilities, Equity.
    One row per filing period.
    """
    data = fetch_company_facts(cik)
    facts = data.get("facts", {})
    us_gaap = facts.get("us-gaap", {})

    metrics_map = {
        "Revenue":           "Revenues",
        "NetIncome":         "NetIncomeLoss",
        "EPS_Basic":         "EarningsPerShareBasic",
        "EPS_Diluted":       "EarningsPerShareDiluted",
        "TotalAssets":       "Assets",
        "TotalLiabilities":  "Liabilities",
        "TotalEquity":       "StockholdersEquity",
    }

    rows = []
    for label, gaap_tag in metrics_map.items():
        tag_data = us_gaap.get(gaap_tag, {})
        units = tag_data.get("units", {})
        for unit_type, entries in units.items():
            for entry in entries:
                rows.append({
                    "cik": cik,
                    "metric": label,
                    "value": entry.get("val"),
                    "fy": entry.get("fy"),
                    "fp": entry.get("fp"),       # fiscal period: Q1, Q2, FY, etc.
                    "filed": entry.get("filed"),
                    "form": entry.get("form"),   # 10-K, 10-Q
                    "unit": unit_type,
                })

    return pl.DataFrame(rows)


# ── Submissions (Filing History) ─────────────────────────────────
def fetch_submissions(cik: str) -> dict:
    """Fetch filing history for a CIK."""
    cik_padded = str(cik).zfill(10)
    url = f"{SEC_BASE}/files/company_tickers_exchange/CIK{cik_padded}.json"
    # SEC changed API — use submissions endpoint
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def fetch_filing_history(cik: str) -> pl.DataFrame:
    """Get recent filings as a DataFrame."""
    data = fetch_submissions(cik)
    recent = data.get("filings", {}).get("recent", {})

    if not recent:
        return pl.DataFrame()

    n = len(recent.get("accessionNumber", []))
    rows = []
    for i in range(n):
        rows.append({
            "accession":        recent["accessionNumber"][i],
            "filing_date":      recent["filingDate"][i],
            "report_date":      recent.get("reportDate", [""])[i],
            "form":             recent["form"][i],
            "primary_document": recent["primaryDocument"][i],
            "description":      recent.get("primaryDocDescription", [""])[i],
        })

    return pl.DataFrame(rows)


# ── Form 4 (Insider Trading) ─────────────────────────────────────
def fetch_insider_trades(cik: str) -> pl.DataFrame:
    """
    Fetch recent Form 4 (insider trades) for a company CIK.
    """
    cik_padded = str(cik).zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    data = resp.json()

    # Form 4s are in the filings list
    recent = data.get("filings", {}).get("recent", {})
    if not recent:
        return pl.DataFrame()

    forms = recent.get("form", [])
    n = len(forms)
    rows = []
    for i in range(n):
        if forms[i] == "4":  # Form 4 = insider transaction
            acc = recent["accessionNumber"][i]
            rows.append({
                "accession":   acc,
                "filing_date": recent["filingDate"][i],
                "issuer_cik":  cik,
                "document_url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{recent['primaryDocument'][i]}"
            })

    return pl.DataFrame(rows)


# ── CIK Lookup ───────────────────────────────────────────────────
def ticker_to_cik(ticker: str) -> str:
    """
    Convert ticker symbol to CIK using SEC company tickers JSON.
    Cached locally for speed.
    """
    cache_path = Path("data/raw/ticker_cik_map.json")

    if cache_path.exists():
        import json
        mapping = json.loads(cache_path.read_text())
        if ticker.upper() in mapping:
            return mapping[ticker.upper()]

    # Download full mapping
    url = "https://www.sec.gov/files/company_tickers.json"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    data = resp.json()

    mapping = {}
    for entry in data.values():
        mapping[entry["ticker"].upper()] = str(entry["cik_str"])

    import json
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(mapping))

    return mapping.get(ticker.upper(), "")
