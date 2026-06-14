"""
QuantForge Research Module

Point-in-time signal research infrastructure:
    FeatureStore     — PIT feature storage (Parquet)
    PointInTimeJoiner — strict temporal alignment (no lookahead)
    ForwardReturnLabeler — multi-horizon forward returns
    SignalStudyRunner — quintile analysis, IC, sharpe, reports
"""

from .feature_store import FeatureStore
from .features import build_award_velocity, trailing_zscore
from .pit_joiner import PointInTimeJoiner
from .forward_returns import ForwardReturnLabeler
from .study_runner import SignalStudyRunner

__all__ = [
    "FeatureStore",
    "PointInTimeJoiner",
    "ForwardReturnLabeler",
    "SignalStudyRunner",
    "build_award_velocity",
    "trailing_zscore",
]
