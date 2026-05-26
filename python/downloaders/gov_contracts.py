"""
Federal procurement data — SAM.gov / FPDS contract awards.
Free, public, no API key for basic search.

Use case: track defense/AI contract award velocity by company,
supplier network analysis, subcontractor activity.
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import polars as pl
import requests

logger = logging.getLogger(__name__)

# SAM.gov API (free, requires account for API key, but public search works)
SAM_API = "https://api.sam.gov/opportunities/v2/search"
# USASpending.gov API (free, no key required for basic access)
USA_SPENDING = "https://api.usaspending.gov/api/v2"

HEADERS = {
    "User-Agent": "QuantForge/0.1 (justin0106@protonmail.com)"
}


def search_contracts(
    keywords: list[str],
    date_range: tuple[str, str] = ("2024-01-01", "2025-12-31"),
    limit: int = 1000
) -> pl.DataFrame:
    """
    Search federal contracts by keyword using USASpending API.

    Example keywords: ["artificial intelligence", "GPU", "CUDA", "missile", "radar"]
    Returns: contract awards with vendor, value, agency, dates
    """

    all_results = []

    for keyword in keywords:
        url = f"{USA_SPENDING}/search/spending_by_award/"

        payload = {
            "filters": {
                "keywords": [keyword],
                "time_period": [
                    {"start_date": date_range[0], "end_date": date_range[1]}
                ],
                "award_type_codes": ["A", "B", "C", "D"],  # Contracts only
            },
            "fields": [
                "Award ID", "Awarding Agency", "Awarding Sub Agency",
                "Recipient Name", "Recipient DUNS", "Description",
                "Period of Performance Start Date", "Period of Performance Current End Date",
                "Award Amount", "Potential Award Value",
            ],
            "limit": limit,
            "page": 1,
            "sort": "Award Amount",
            "order": "desc"
        }

        try:
            resp = requests.post(url, json=payload, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            for award in data.get("results", []):
                all_results.append({
                    "award_id": award.get("Award ID", ""),
                    "agency": award.get("Awarding Agency", ""),
                    "sub_agency": award.get("Awarding Sub Agency", ""),
                    "vendor_name": award.get("Recipient Name", ""),
                    "vendor_duns": award.get("Recipient DUNS", ""),
                    "description": award.get("Description", ""),
                    "start_date": award.get("Period of Performance Start Date"),
                    "end_date": award.get("Period of Performance Current End Date"),
                    "award_amount": award.get("Award Amount"),
                    "potential_value": award.get("Potential Award Value"),
                    "keyword": keyword,
                })

        except Exception as e:
            logger.error("Contract search failed for '%s': %s", keyword, e)

        time.sleep(0.6)  # Rate limiting

    if not all_results:
        return pl.DataFrame()

    df = pl.DataFrame(all_results)
    return df.sort("award_amount", descending=True)


def fetch_defense_contracts_by_vendor(
    vendor_names: list[str],
    start_date: str = "2023-01-01",
    end_date: str = "2025-12-31"
) -> pl.DataFrame:
    """
    Fetch DoD/Federal contracts for specific defense vendors.

    Common tickers → vendor name mapping:
    LMT → Lockheed Martin
    RTX → Raytheon Technologies
    NOC → Northrop Grumman
    GD  → General Dynamics
    BA  → Boeing
    LHX → L3Harris
    HII → Huntington Ingalls
    """

    url = f"{USA_SPENDING}/search/spending_by_award/"

    all_results = []

    for vendor in vendor_names:
        payload = {
            "filters": {
                "recipient_search_text": [vendor],
                "time_period": [
                    {"start_date": start_date, "end_date": end_date}
                ],
                "award_type_codes": ["A", "B", "C", "D"],
            },
            "fields": [
                "Award ID", "Awarding Agency", "Awarding Sub Agency",
                "Recipient Name", "Description",
                "Period of Performance Start Date",
                "Award Amount", "Potential Award Value",
                "Naics Description", "PSC Description",
            ],
            "limit": 500,
            "page": 1,
            "sort": "Award Amount",
            "order": "desc"
        }

        try:
            resp = requests.post(url, json=payload, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            for award in data.get("results", []):
                all_results.append({
                    "vendor": vendor,
                    "award_id": award.get("Award ID"),
                    "agency": award.get("Awarding Agency"),
                    "description": award.get("Description"),
                    "amount": award.get("Award Amount", 0) or 0,
                    "potential_value": award.get("Potential Award Value", 0) or 0,
                    "start_date": award.get("Period of Performance Start Date"),
                    "naics": award.get("Naics Description"),
                    "psc": award.get("PSC Description"),
                })

        except Exception as e:
            logger.error("Vendor search failed for '%s': %s", vendor, e)

        time.sleep(0.7)

    return pl.DataFrame(all_results)


def contract_award_velocity(
    df: pl.DataFrame,
    group_by: str = "vendor",
    window_days: int = 90
) -> pl.DataFrame:
    """
    Compute rolling contract award velocity.

    For each vendor, compute:
    - Total awarded in last N days
    - Number of new awards in last N days
    - Average award size
    - YoY growth rate
    """
    if df.is_empty():
        return df

    # Ensure datetime
    df = df.with_columns(pl.col("start_date").cast(pl.Date))

    # Group by vendor and quarter
    df = df.with_columns(
        pl.col("start_date").dt.truncate("1mo").alias("month")
    )

    velocity = df.group_by(["vendor", "month"]).agg([
        pl.col("amount").sum().alias("monthly_awards"),
        pl.col("award_id").n_unique().alias("award_count"),
        pl.col("amount").mean().alias("avg_award_size"),
    ]).sort(["vendor", "month"])

    # Rolling 3-month total
    velocity = velocity.with_columns(
        pl.col("monthly_awards")
          .rolling_sum(window_size=3, min_periods=1)
          .over("vendor")
          .alias("trailing_3mo_total"),
        pl.col("award_count")
          .rolling_sum(window_size=3, min_periods=1)
          .over("vendor")
          .alias("trailing_3mo_count"),
    )

    return velocity


# ── Agency spending trends ────────────────────────────────────────
def agency_spending_trends(
    agencies: list[str] = None
) -> pl.DataFrame:
    """
    Get agency-level spending profiles.
    Defaults to defense-related agencies.
    """
    if agencies is None:
        agencies = [
            "Department of Defense",
            "Department of the Air Force",
            "Department of the Navy",
            "Department of the Army",
            "Defense Advanced Research Projects Agency",
            "Missile Defense Agency",
            "Space Development Agency",
            "National Aeronautics and Space Administration",
        ]

    url = f"{USA_SPENDING}/api/v2/agency/{agencies[0]}/obligations_by_award_category/"

    results = []
    for agency in agencies:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                for cat in data.get("results", []):
                    results.append({
                        "agency": agency,
                        "category": cat.get("category", ""),
                        "obligated_amount": cat.get("aggregated_amount", 0)
                    })
        except Exception as e:
            logger.error("Agency lookup failed for %s: %s", agency, e)

    return pl.DataFrame(results)
