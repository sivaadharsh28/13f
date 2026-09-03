from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
SECTOR_OVERRIDE_PATH = DATA_DIR / "sector_overrides.csv"
SEC_USER_AGENT_ENV = "THIRTEENF_SEC_USER_AGENT"


def sec_user_agent(explicit: str | None = None) -> str:
    """Return a declared SEC user-agent or fail before making a request."""
    value = (explicit or os.getenv(SEC_USER_AGENT_ENV, "")).strip()
    if not value or "@" not in value:
        raise ValueError(
            f"Set {SEC_USER_AGENT_ENV} to 'Organization contact@example.com' "
            "or pass an explicit SEC user-agent."
        )
    return value
