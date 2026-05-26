"""
Job posting data — scrape public job boards for hiring signals.

Sources:
- USAJobs (federal): free API, government jobs → defense/AI roles
- RSS/Atom feeds from company career pages
- LinkedIn public job pages (polite scraping)

Signal: hiring acceleration by skill category → predicts revenue/investment
"""

import logging
import time
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import polars as pl
import requests

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "QuantForge/0.1 (research bot; justin0106@protonmail.com)"
}


# ── USAJobs API (free, no key required) ───────────────────────────
def fetch_usajobs(
    keywords: list[str],
    max_results: int = 500
) -> pl.DataFrame:
    """
    Search federal job postings for defense/AI/engineering roles.

    Keywords examples: ["artificial intelligence", "CUDA", "GPU",
                        "machine learning", "cybersecurity", "missile",
                        "radar", "aerospace", "C++", "embedded"]
    """
    all_results = []

    for keyword in keywords:
        url = "https://data.usajobs.gov/api/search"
        params = {
            "Keyword": keyword,
            "ResultsPerPage": min(max_results, 100),
            "SortField": "opendate",
            "SortDirection": "desc",
        }

        try:
            resp = requests.get(url, params=params, headers={
                **HEADERS,
                "Host": "data.usajobs.gov",
                "User-Agent": "QuantForge/0.1 (justin0106@protonmail.com)"
            }, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("SearchResult", {}).get("SearchResultItems", []):
                match = item.get("MatchedObjectDescriptor", {})
                positions = match.get("PositionFormattedDescription", [])
                desc_text = " ".join(
                    p.get("Value", "") for p in positions
                    if p.get("Label") == "Duties Summary"
                )[:500]

                all_results.append({
                    "job_title": match.get("PositionTitle", ""),
                    "agency": match.get("DepartmentName", ""),
                    "location": match.get("PositionLocationDisplay", ""),
                    "post_date": match.get("PublicationStartDate", ""),
                    "close_date": match.get("ApplicationCloseDate", ""),
                    "salary_min": float(match.get("PositionRemuneration", [{}])[0].get("MinimumRange", "0").replace("$", "").replace(",", "") or 0),
                    "salary_max": float(match.get("PositionRemuneration", [{}])[0].get("MaximumRange", "0").replace("$", "").replace(",", "") or 0),
                    "description": desc_text,
                    "keyword": keyword,
                })

        except Exception as e:
            logger.error("USAJobs search failed for '%s': %s", keyword, e)

        time.sleep(0.5)

    if not all_results:
        return pl.DataFrame()

    df = pl.DataFrame(all_results)
    df = df.with_columns(pl.col("post_date").cast(pl.Date))
    return df.sort("post_date", descending=True)


# ── Skill extraction from job descriptions ────────────────────────
SKILL_PATTERNS = {
    "ai_ml": [
        r"machine learning", r"deep learning", r"artificial intelligence",
        r"\bAI\b", r"neural network", r"transformer", r"LLM", r"large language model",
        r"PyTorch", r"TensorFlow", r"JAX",
    ],
    "gpu_hpc": [
        r"\bGPU\b", r"\bCUDA\b", r"\bHPC\b", r"high performance computing",
        r"parallel computing", r"accelerator", r"\bFPGA\b",
    ],
    "defense_systems": [
        r"missile", r"radar", r"weapon", r"\bC4ISR\b", r"\bISR\b",
        r"electronic warfare", r"aerospace", r"avionics", r"\bDoD\b",
        r"defense", r"munitions", r"ordnance",
    ],
    "cyber": [
        r"cyber\w*", r"infosec", r"information security",
        r"penetration test", r"vulnerability", r"\bCISSP\b",
        r"zero trust", r"\bSOC\b", r"\bSIEM\b",
    ],
    "software_engineering": [
        r"\bC\+\+\b", r"\bRust\b", r"\bPython\b", r"\bJava\b",
        r"software engineer", r"\bDevOps\b", r"\bCI/CD\b",
        r"microservices", r"\bAPI\b", r"\bbackend\b",
    ],
    "data_infra": [
        r"data engineer", r"data pipeline", r"\bETL\b",
        r"\bSQL\b", r"\bDuckDB\b", r"\bPostgreSQL\b",
        r"\bKafka\b", r"\bSpark\b", r"data lake",
    ],
    "embedded": [
        r"embedded", r"firmware", r"\bRTOS\b", r"microcontroller",
        r"\bVHDL\b", r"\bVerilog\b", r"\bARM\b", r"\bRISC-V\b",
    ],
    "cloud": [
        r"\bAWS\b", r"\bAzure\b", r"\bGCP\b", r"cloud",
        r"\bKubernetes\b", r"\bk8s\b", r"\bDocker\b", r"container",
    ],
    "clearance": [
        r"security clearance", r"top secret", r"\bTS/SCI\b",
        r"secret clearance", r"\bSCI\b", r"polygraph",
        r"\bSAP\b", r"special access",
    ],
}


def extract_skills(text: str) -> dict[str, int]:
    """Count skill mentions in job description text."""
    text_lower = text.lower()
    counts = {}
    for category, patterns in SKILL_PATTERNS.items():
        count = sum(1 for p in patterns if re.search(p, text_lower))
        counts[category] = count
    return counts


def skill_acceleration(
    jobs_df: pl.DataFrame,
    window_days: int = 30
) -> pl.DataFrame:
    """
    Compute hiring acceleration by skill category.

    For each skill category, compute:
    - Postings per month
    - MoM change
    - Rolling 3-month trend
    """
    if jobs_df.is_empty():
        return jobs_df

    # Extract skills from all descriptions
    skill_rows = []
    for row in jobs_df.iter_rows(named=True):
        desc = row.get("description", "") or ""
        skills = extract_skills(desc)
        for cat, count in skills.items():
            if count > 0:
                skill_rows.append({
                    "post_date": row.get("post_date"),
                    "agency": row.get("agency"),
                    "skill_category": cat,
                    "count": count,
                })

    if not skill_rows:
        return pl.DataFrame()

    skills_df = pl.DataFrame(skill_rows)

    # Aggregated by month
    if "post_date" in skills_df.columns:
        skills_df = skills_df.with_columns(
            pl.col("post_date").cast(pl.Date).dt.truncate("1mo").alias("month")
        )

        trends = skills_df.group_by(["skill_category", "month"]).agg([
            pl.col("count").sum().alias("total_mentions"),
            pl.len().alias("posting_count"),
        ]).sort(["skill_category", "month"])

        # MoM change
        trends = trends.with_columns(
            pl.col("total_mentions")
              .pct_change()
              .over("skill_category")
              .alias("mom_change_pct"),
            pl.col("posting_count")
              .rolling_mean(window_size=3, min_periods=1)
              .over("skill_category")
              .alias("rolling_3mo_avg"),
        )

        return trends

    return skills_df


# ── Combined hiring signal ────────────────────────────────────────
def build_hiring_signal(
    jobs_df: pl.DataFrame,
    date_col: str = "post_date"
) -> pl.DataFrame:
    """
    Build a composite hiring signal from job postings.

    Returns a DataFrame with one row per month per skill category
    including acceleration metrics.
    """
    return skill_acceleration(jobs_df)
