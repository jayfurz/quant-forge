"""
Derived Feature Engineering — the core differentiator.

Transforms raw data from multiple sources into structured signals
that can be backtested against price/volatility/earnings outcomes.

Philosophy: "The data is public, but the feature engineering is yours."
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import polars as pl

logger = logging.getLogger(__name__)


# ── SEC Filing Diff Score ─────────────────────────────────────────
def filing_diff_score(
    current_text: str,
    prior_text: str,
    section: str = "risk_factors"
) -> dict:
    """
    Compute a structured diff score between two consecutive filings.

    Returns:
    - pct_changed: percentage of tokens changed
    - pct_added: percentage of new tokens
    - pct_removed: percentage of removed tokens
    - severity_score: weighted by risk-related language
    - new_risk_count: count of newly introduced risk phrases
    """
    current_tokens = set(current_text.lower().split())
    prior_tokens = set(prior_text.lower().split())

    if not prior_tokens:
        return {"pct_changed": 0.0, "severity_score": 0.0, "new_risk_count": 0}

    added = current_tokens - prior_tokens
    removed = prior_tokens - current_tokens
    total_unique = len(current_tokens | prior_tokens)

    pct_changed = len(added | removed) / max(total_unique, 1) * 100

    # Risk severity keywords
    RISK_SEVERITY = {
        "severe": 3, "critical": 3, "material": 2, "significant": 2,
        "adverse": 2, "substantial": 2, "cyber": 3, "breach": 3,
        "compliance": 2, "violation": 3, "litigation": 2, "regulatory": 2,
        "sanction": 3, "investigation": 2, "penalty": 3, "suspension": 3,
        "default": 3, "bankruptcy": 4, "insolvency": 4, "going concern": 5,
        "restructuring": 2, "impairment": 2, "write-down": 2,
        "supply chain disruption": 2, "shortage": 2, "tariff": 2,
        "geopolitical": 2, "conflict": 2, "sanction": 3,
    }

    severity = 0
    new_risks = 0
    for token in added:
        for risk_word, weight in RISK_SEVERITY.items():
            if risk_word in token:
                severity += weight
                new_risks += 1
                break

    return {
        "pct_changed": round(pct_changed, 2),
        "pct_added": round(len(added) / max(total_unique, 1) * 100, 2),
        "pct_removed": round(len(removed) / max(total_unique, 1) * 100, 2),
        "severity_score": severity,
        "new_risk_count": new_risks,
    }


# ── AI Hiring Acceleration Score ──────────────────────────────────
def ai_hiring_signal(
    skills_trends: pl.DataFrame,
    lookback_months: int = 6
) -> pl.DataFrame:
    """
    Compute AI hiring acceleration score from skill trends.

    Combines:
    - AI/ML hiring velocity
    - GPU/HPC hiring (infrastructure buildout signal)
    - Security clearance hiring (defense project ramp)
    - Data infrastructure hiring (platform maturity)
    """

    if skills_trends.is_empty():
        return pl.DataFrame()

    # Focus on forward-looking categories
    signal_cats = ["ai_ml", "gpu_hpc", "cyber", "data_infra", "clearance"]

    filtered = skills_trends.filter(
        pl.col("skill_category").is_in(signal_cats)
    )

    if filtered.is_empty():
        return pl.DataFrame()

    # Composite score: weighted sum of z-scored posting counts
    latest = filtered.group_by("skill_category").agg([
        pl.col("total_mentions").tail(lookback_months).sum().alias("recent_mentions"),
        pl.col("mom_change_pct").tail(lookback_months).mean().alias("avg_mom_change"),
    ])

    if latest.is_empty():
        return pl.DataFrame()

    # Normalize to get composite
    total = latest["recent_mentions"].sum()
    if total > 0:
        latest = latest.with_columns(
            (pl.col("recent_mentions") / total).alias("weight")
        )

    composite = latest.select([
        (pl.col("recent_mentions") * pl.col("weight")).sum().alias("ai_hiring_index"),
        (pl.col("avg_mom_change") * pl.col("weight")).sum().alias("ai_hiring_momentum"),
    ])

    return composite


# ── Defense Contract Award Velocity ───────────────────────────────
def defense_contract_signal(
    contracts: pl.DataFrame,
    lookback_days: int = 90
) -> pl.DataFrame:
    """
    Compute defense contract velocity signal.

    Key features:
    - Recent award total vs historical average
    - Acceleration (2nd derivative of award amounts)
    - Award size concentration (big programs starting?)
    - Multi-agency diversification
    """

    if contracts.is_empty():
        return pl.DataFrame()

    # Ensure date column
    contracts = contracts.with_columns(
        pl.col("start_date").cast(pl.Date)
    )

    now = datetime.now().date()
    cutoff = now - timedelta(days=lookback_days)

    recent = contracts.filter(pl.col("start_date") >= cutoff)
    historical = contracts.filter(pl.col("start_date") < cutoff)

    recent_total = recent["amount"].sum() if not recent.is_empty() else 0
    hist_total = historical["amount"].sum() if not historical.is_empty() else 0

    # Expected recent (pro-rata)
    if not historical.is_empty():
        hist_days = (
            historical["start_date"].max() - historical["start_date"].min()
        ).days
        if hist_days > 0:
            daily_rate = hist_total / max(hist_days, 1)
            expected = daily_rate * lookback_days
            surprise = (recent_total - expected) / max(expected, 1) if expected > 0 else 0
        else:
            surprise = 0.0
    else:
        surprise = 0.0

    # Award concentration (HHI)
    vendor_totals = (
        recent.group_by("vendor")
        .agg(pl.col("amount").sum().alias("vendor_total"))
        if not recent.is_empty() else pl.DataFrame()
    )

    hhi = 0.0
    if not vendor_totals.is_empty() and recent_total > 0:
        hhi = vendor_totals.with_columns(
            ((pl.col("vendor_total") / recent_total * 100) ** 2).alias("squared_share")
        )["squared_share"].sum()

    return pl.DataFrame([{
        "recent_90d_awards": recent_total,
        "expected_90d_awards": expected if 'expected' in dir() else 0.0,
        "contract_surprise_ratio": surprise,
        "award_concentration_hhi": hhi,
        "unique_agencies": contracts.filter(
            pl.col("start_date") >= cutoff
        )["agency"].n_unique() if not contracts.is_empty() else 0,
        "avg_award_size": recent["amount"].mean() if not recent.is_empty() else 0,
    }])


# ── Earnings Call Evasiveness Score ───────────────────────────────
EVASIVE_PATTERNS = [
    r"not going to comment",
    r"can't disclose",
    r"no comment",
    r"decline to answer",
    r"don't have visibility",
    r"too early to say",
    r"difficult to predict",
    r"uncertain",
    r"not providing guidance",
    r"won't speculate",
    r"competitive reasons",
    r"we'll see how it plays out",
    r"hard to quantify",
]


def evasiveness_score(transcript: str) -> dict:
    """
    Score how evasive management language is in an earnings call.

    High evasiveness may precede volatility or negative surprises.
    """
    import re

    text_lower = transcript.lower()
    total_words = len(text_lower.split())

    evasive_count = 0
    matches = []
    for pattern in EVASIVE_PATTERNS:
        found = re.findall(pattern, text_lower)
        evasive_count += len(found)
        matches.extend(found)

    # Per 10k words, but cap at reasonable max (short texts inflate this)
    evasiveness = (evasive_count / max(total_words, 1)) * 10000
    evasiveness = min(evasiveness, 100.0)  # cap to prevent short-text explosion

    return {
        "evasive_phrase_count": evasive_count,
        "evasiveness_score": round(evasiveness, 2),
        "sample_matches": matches[:5],
    }


# ── Composite Signal Builder ──────────────────────────────────────
def build_composite_signal(
    symbol: str,
    sec_filing_score: Optional[dict] = None,
    hiring_score: Optional[pl.DataFrame] = None,
    contract_score: Optional[pl.DataFrame] = None,
    evasiveness: Optional[dict] = None,
    price_data: Optional[pl.DataFrame] = None,
) -> dict:
    """
    Combine all derived features into a single composite signal.

    Weights (configurable):
    - Filing changes: 25%
    - Hiring acceleration: 25%
    - Contract velocity: 25%
    - Management evasiveness: 15%
    - Price/technical overlay: 10%
    """

    signal = {
        "symbol": symbol,
        "timestamp": datetime.now().isoformat(),
        "components": {},
    }

    total_score = 0.0
    total_weight = 0.0

    # Filing diff score → standardized to ~[-3, +3]
    if sec_filing_score:
        severity = min(sec_filing_score.get("severity_score", 0), 30) / 10.0
        change = sec_filing_score.get("pct_changed", 0) / 10.0
        filing_signal = -(severity * 0.7 + change * 0.3)  # Negative: more risk language
        signal["components"]["filing_risk"] = filing_signal
        total_score += filing_signal * 0.25
        total_weight += 0.25

    # Hiring signal → standardized
    if hiring_score is not None and not hiring_score.is_empty():
        momentum = hiring_score["ai_hiring_momentum"][0] if "ai_hiring_momentum" in hiring_score else 0.0
        # Clip to [-3, +3]
        hiring_signal = np.clip(momentum * 5, -3.0, 3.0) if not np.isnan(momentum) else 0.0
        signal["components"]["ai_hiring"] = hiring_signal
        total_score += hiring_signal * 0.25
        total_weight += 0.25

    # Contract velocity
    if contract_score is not None and not contract_score.is_empty():
        surprise = contract_score["contract_surprise_ratio"][0] if "contract_surprise_ratio" in contract_score else 0.0
        contract_signal = np.clip(surprise * 2, -3.0, 3.0) if not np.isnan(surprise) else 0.0
        signal["components"]["contract_awards"] = contract_signal
        total_score += contract_signal * 0.25
        total_weight += 0.25

    # Evasiveness score
    if evasiveness:
        ev_score = evasiveness.get("evasiveness_score", 0)
        # Normalize: higher evasiveness = negative signal
        ev_signal = np.clip(-ev_score / 5.0, -3.0, 3.0)
        signal["components"]["evasiveness"] = ev_signal
        total_score += ev_signal * 0.15
        total_weight += 0.15

    # Price overlay (volatility regime, momentum)
    if price_data is not None and not price_data.is_empty():
        closes = price_data["close"].to_list()
        if len(closes) > 20:
            sma20 = sum(closes[-20:]) / 20
            latest = closes[-1]
            mom = (latest / sma20 - 1.0) * 100
            price_signal = np.clip(mom, -3.0, 3.0)
            signal["components"]["price_momentum"] = price_signal
            total_score += price_signal * 0.10
            total_weight += 0.10

    signal["composite_score"] = (
        total_score / max(total_weight, 0.01) if total_weight > 0 else 0.0
    )
    signal["interpretation"] = interpret_signal(signal["composite_score"])

    return signal


def interpret_signal(score: float) -> str:
    if score > 1.5:
        return "STRONG_BULLISH"
    elif score > 0.5:
        return "BULLISH"
    elif score > -0.5:
        return "NEUTRAL"
    elif score > -1.5:
        return "BEARISH"
    else:
        return "STRONG_BEARISH"
