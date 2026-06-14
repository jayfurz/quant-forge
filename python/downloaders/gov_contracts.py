"""
Federal procurement data — SAM.gov / USASpending.gov contract awards.
Free, public, no API key for basic search.

Fixed for current API field names (UEI instead of DUNS, Start Date instead of PoP Start Date).
"""

import calendar
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import polars as pl
import requests

logger = logging.getLogger(__name__)

USA_SPENDING = "https://api.usaspending.gov/api/v2"
HEADERS = {
    "User-Agent": "QuantForge/0.1 (justin0106@protonmail.com)",
    "Content-Type": "application/json",
}


def search_contracts(
    keywords: list[str],
    date_range: tuple[str, str] = ("2024-01-01", "2025-12-31"),
    limit: int = 500
) -> pl.DataFrame:
    """Search federal contracts by keyword using USASpending API."""

    all_results = []

    for keyword in keywords:
        url = f"{USA_SPENDING}/search/spending_by_award/"
        payload = {
            "filters": {
                "keywords": [keyword],
                "time_period": [
                    {"start_date": date_range[0], "end_date": date_range[1]}
                ],
                "award_type_codes": ["A", "B", "C", "D"],
            },
            "fields": [
                "Award ID", "Awarding Agency", "Awarding Sub Agency",
                "Recipient Name", "Recipient UEI", "Description",
                "Start Date", "End Date",
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
                    "vendor_uei": award.get("Recipient UEI", ""),
                    "description": award.get("Description", ""),
                    "start_date": award.get("Start Date"),
                    "end_date": award.get("End Date"),
                    "award_amount": float(award.get("Award Amount", 0) or 0),
                    "potential_value": float(award.get("Potential Award Value", 0) or 0),
                    "keyword": keyword,
                })

        except Exception as e:
            logger.error("Contract search failed for '%s': %s", keyword, e)

        time.sleep(0.6)

    if not all_results:
        return pl.DataFrame()

    return pl.DataFrame(all_results).sort("award_amount", descending=True)


def fetch_defense_contracts(
    vendor_names: list[str],
    start_date: str = "2023-01-01",
    end_date: str = "2025-12-31"
) -> pl.DataFrame:
    """
    Fetch federal contracts for specific defense vendors via keyword search.

    Ticker → vendor name:
      LMT → Lockheed Martin, RTX → Raytheon, NOC → Northrop Grumman,
      GD → General Dynamics, BA → Boeing, LHX → L3Harris, HII → Huntington Ingalls
    """
    url = f"{USA_SPENDING}/search/spending_by_award/"
    all_results = []

    for vendor in vendor_names:
        payload = {
            "filters": {
                "keywords": [vendor],
                "time_period": [
                    {"start_date": start_date, "end_date": end_date}
                ],
                "award_type_codes": ["A", "B", "C", "D"],
            },
            "fields": [
                "Award ID", "Awarding Agency", "Awarding Sub Agency",
                "Recipient Name", "Description",
                "Start Date", "End Date",
                "Award Amount", "Potential Award Value",
                "NAICS Description", "Product Service Code (PSC) Description",
            ],
            "limit": 100,
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
                    "amount": float(award.get("Award Amount", 0) or 0),
                    "potential_value": float(award.get("Potential Award Value", 0) or 0),
                    "start_date": award.get("Start Date"),
                    "end_date": award.get("End Date"),
                    "naics": award.get("NAICS Description"),
                    "psc": award.get("Product Service Code (PSC) Description"),
                })

        except Exception as e:
            logger.error("Vendor search failed for '%s': %s", vendor, e)

        time.sleep(0.7)

    return pl.DataFrame(all_results)


# Backwards compat alias
fetch_defense_contracts_by_vendor = fetch_defense_contracts


def _fiscal_to_calendar_month_end(fiscal_year: int, fiscal_month: int) -> date:
    """
    USAspending groups by *fiscal* month (FY starts in October, so fiscal
    month 1 = October of FY-1). Return the calendar month-end date — the point
    at which that month's obligations are fully booked.
    """
    cal_month = (fiscal_month + 8) % 12 + 1           # FY m1 -> Oct(10)
    cal_year = fiscal_year - 1 if fiscal_month <= 3 else fiscal_year
    last_day = calendar.monthrange(cal_year, cal_month)[1]
    return date(cal_year, cal_month, last_day)


def fetch_monthly_obligations_by_vendor(
    vendor_names: list[str],
    start_date: str = "2015-01-01",
    end_date: str = "2025-12-31",
) -> pl.DataFrame:
    """
    Fetch monthly federal contract obligation totals per vendor via the
    ``spending_over_time`` endpoint.

    This is the right granularity for an award-velocity feature: the server
    aggregates every transaction into monthly sums, so there is no pagination /
    truncation risk (a single prime can book >5,000 transactions per year, which
    would silently drop the oldest history from the transaction endpoint). One
    request per vendor, complete coverage, fast enough for a decade of history.

    Returns columns:
        vendor, month (calendar month-end Date), amount
    """
    url = f"{USA_SPENDING}/search/spending_over_time/"
    rows = []

    for vendor in vendor_names:
        payload = {
            "group": "month",
            "filters": {
                "keywords": [vendor],
                "time_period": [{"start_date": start_date, "end_date": end_date}],
                "award_type_codes": ["A", "B", "C", "D"],
            },
        }
        try:
            resp = requests.post(url, json=payload, headers=HEADERS, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Monthly obligation fetch failed for '%s': %s", vendor, e)
            continue

        results = data.get("results", [])
        for r in results:
            tp = r.get("time_period", {})
            try:
                fy = int(tp.get("fiscal_year"))
                fm = int(tp.get("month"))
                amount = float(r.get("aggregated_amount", 0) or 0)
            except (TypeError, ValueError):
                continue
            rows.append({
                "vendor": vendor,
                "month": _fiscal_to_calendar_month_end(fy, fm),
                "amount": amount,
            })
        logger.info("  %s: %d monthly buckets", vendor, len(results))
        time.sleep(0.3)

    if not rows:
        return pl.DataFrame()

    return pl.DataFrame(rows).sort(["vendor", "month"])


def _yearly_windows(start_date: str, end_date: str) -> list[tuple[str, str]]:
    """Split [start, end] into ≤1-year sub-windows (inclusive)."""
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    windows = []
    cursor = start
    while cursor <= end:
        nxt = min(date(cursor.year, 12, 31), end)
        windows.append((cursor.isoformat(), nxt.isoformat()))
        cursor = date(cursor.year + 1, 1, 1)
    return windows


def fetch_transactions_by_vendor(
    vendor_names: list[str],
    start_date: str = "2023-01-01",
    end_date: str = "2025-12-31",
    max_pages_per_window: int = 50,
    page_size: int = 100,
    chunk_years: bool = True,
) -> pl.DataFrame:
    """
    Fetch federal contract *transactions* (obligation actions) per vendor.

    Unlike :func:`fetch_defense_contracts`, which hits the award-level endpoint
    and returns each award's *current cumulative* obligated amount stamped at a
    single period-of-performance start date (a lookahead trap — see
    reports/contract_award_velocity/RESEARCH_NOTES.md), this hits the
    transaction-level endpoint. Each row is one obligation booked on a specific
    ``action_date``, which is the point-in-time-correct event timestamp for
    building an award-velocity feature.

    For long windows a single prime can have more transactions than
    ``max_pages_per_window * page_size``; sorting by Action Date desc would then
    silently drop the *oldest* history and bias the trailing baseline. To keep
    coverage complete we fetch one calendar-year sub-window at a time
    (``chunk_years``), paginating each to exhaustion.

    Returns columns:
        vendor, recipient_name, award_id, amount, action_date, agency
    """
    url = f"{USA_SPENDING}/search/spending_by_transaction/"
    rows = []
    windows = _yearly_windows(start_date, end_date) if chunk_years else [(start_date, end_date)]

    for vendor in vendor_names:
        vendor_rows = 0
        for win_start, win_end in windows:
            for page in range(1, max_pages_per_window + 1):
                payload = {
                    "filters": {
                        "keywords": [vendor],
                        "time_period": [{"start_date": win_start, "end_date": win_end}],
                        "award_type_codes": ["A", "B", "C", "D"],
                    },
                    "fields": [
                        "Transaction Amount", "Action Date", "Recipient Name",
                        "Award ID", "Awarding Agency", "Mod",
                    ],
                    "limit": page_size,
                    "page": page,
                    "sort": "Action Date",
                    "order": "desc",
                }
                try:
                    resp = requests.post(url, json=payload, headers=HEADERS, timeout=30)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    logger.error("Transaction search failed for '%s' %s..%s (page %d): %s",
                                 vendor, win_start, win_end, page, e)
                    break

                results = data.get("results", [])
                for tx in results:
                    try:
                        amount = float(tx.get("Transaction Amount", 0) or 0)
                    except (ValueError, TypeError):
                        amount = 0.0
                    rows.append({
                        "vendor": vendor,
                        "recipient_name": tx.get("Recipient Name", ""),
                        "award_id": tx.get("Award ID", ""),
                        "amount": amount,
                        "action_date": tx.get("Action Date"),
                        "agency": tx.get("Awarding Agency", ""),
                    })
                vendor_rows += len(results)

                if not data.get("page_metadata", {}).get("hasNext"):
                    break
                time.sleep(0.25)
        logger.info("  %s: %d transactions", vendor, vendor_rows)
        time.sleep(0.4)

    if not rows:
        return pl.DataFrame()

    return pl.DataFrame(rows).sort(["vendor", "action_date"])


def contract_award_velocity(
    df: pl.DataFrame,
    group_by: str = "vendor",
    window_days: int = 90
) -> pl.DataFrame:
    """Compute rolling contract award velocity per vendor."""

    if df.is_empty() or "start_date" not in df.columns:
        return df

    df = df.with_columns(pl.col("start_date").cast(pl.Date))
    df = df.with_columns(pl.col("start_date").dt.truncate("1mo").alias("month"))

    velocity = df.group_by(["vendor", "month"]).agg([
        pl.col("amount").sum().alias("monthly_awards"),
        pl.col("award_id").n_unique().alias("award_count"),
        pl.col("amount").mean().alias("avg_award_size"),
    ]).sort(["vendor", "month"])

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
