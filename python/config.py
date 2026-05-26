"""
QuantForge config and credential loader.
Reads from .env, environment variables, or explicit config.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Config:
    # ── API Keys ──────────────────────────────────────────────
    fred_api_key: str = ""
    usajobs_api_key: str = ""
    usajobs_email: str = ""

    # ── Paths ─────────────────────────────────────────────────
    data_root: Path = Path("data")
    raw_dir: Path = field(default_factory=lambda: Path("data/raw"))
    clean_dir: Path = field(default_factory=lambda: Path("data/clean"))
    market_data_dir: Path = field(default_factory=lambda: Path("data/market_data"))

    # ── Rate Limiting ─────────────────────────────────────────
    download_delay_s: float = 0.5
    sec_rate_limit: int = 10  # req/sec

    # ── Simulation Defaults ───────────────────────────────────
    initial_capital: float = 100_000.0
    commission_per_share: float = 0.005
    slippage_bps: float = 2.0


def load_config(env_path: str | None = None) -> Config:
    """Load config from .env file and environment variables."""

    # Try to load .env from project root
    if env_path is None:
        # Search upward from cwd for .env
        search = Path.cwd()
        for _ in range(5):
            candidate = search / ".env"
            if candidate.exists():
                env_path = str(candidate)
                break
            if search.parent == search:
                break
            search = search.parent

    if env_path:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

    return Config(
        fred_api_key=os.environ.get("FRED_API_KEY", ""),
        usajobs_api_key=os.environ.get("USAJOBS_API_KEY", ""),
        usajobs_email=os.environ.get("USAJOBS_EMAIL", ""),
    )


# Singleton
_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config
