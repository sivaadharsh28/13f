"""Canonical manager registry.

CIKs are SEC filer identities. Keep this file as the single source of truth;
the JSON copy is an exported artifact produced by ``write_fund_config``.
"""

from __future__ import annotations

from typing import Any


FUND_CONFIG: dict[str, dict[str, Any]] = {
    "PSC": {"name": "Pershing Square Capital Management, L.P.", "display_name": "Bill Ackman - Pershing Square", "source": "sec", "fallback_source": "dataroma", "fund_code": "psc", "cik": "0001336528", "aliases": ["PERSHING SQUARE CAPITAL MANAGEMENT, L.P."]},
    "VFC": {"name": "Valley Forge Capital Management, LP", "display_name": "Valley Forge Capital Management", "source": "sec", "fallback_source": "dataroma", "fund_code": "VFC", "cik": "0001697868", "aliases": ["VALLEY FORGE CAPITAL MANAGEMENT, LP", "VALLEY FORGE ADVISORS, L.P."]},
    "AM": {"name": "Appaloosa LP", "display_name": "David Tepper - Appaloosa", "source": "sec", "fallback_source": "dataroma", "fund_code": "AM", "cik": "0001656456", "aliases": ["APPALOOSA LP"], "strategy_horizon_trading_days": 63},
    "AC": {"name": "Akre Capital Management LLC", "display_name": "Chuck Akre - Akre Capital", "source": "sec", "fallback_source": "dataroma", "fund_code": "AC", "cik": "0001112520", "aliases": ["AKRE CAPITAL MANAGEMENT LLC"]},
    "BRK": {"name": "Berkshire Hathaway Inc", "display_name": "Warren Buffett - Berkshire", "source": "sec", "fallback_source": "dataroma", "fund_code": "BRK", "cik": "0001067983", "aliases": ["BERKSHIRE HATHAWAY INC"]},
    "HC": {"name": "Himalaya Capital Management LLC", "display_name": "Li Lu - Himalaya", "source": "sec", "fallback_source": "dataroma", "fund_code": "HC", "cik": "0001709323", "aliases": ["HIMALAYA CAPITAL MANAGEMENT LLC"]},
    "TCI": {"name": "TCI Fund Management Ltd", "display_name": "Chris Hohn - TCI Fund", "source": "sec", "fallback_source": "dataroma", "fund_code": "tci", "cik": "0001647251", "aliases": ["TCI FUND MANAGEMENT LTD"]},
    "DA": {"name": "Dorsey Asset Management, LLC", "display_name": "Pat Dorsey - Dorsey Asset", "source": "sec", "fallback_source": "dataroma", "fund_code": "DA", "cik": "0001671657", "aliases": ["DORSEY ASSET MANAGEMENT, LLC"]},
    "DUQ": {"name": "Duquesne Family Office LLC", "display_name": "Stanley Druckenmiller - Duquesne", "source": "sec", "fallback_source": None, "cik": "0001536411", "aliases": ["DUQUESNE FAMILY OFFICE LLC"], "strategy_horizon_trading_days": 63},
    "THIEL": {"name": "Thiel Macro LLC", "display_name": "Peter Thiel - Thiel Macro", "source": "sec", "fallback_source": None, "cik": "0001562087", "aliases": ["THIEL MACRO LLC"], "strategy_horizon_trading_days": 63},
}


def normalize_cik(cik: str | int) -> str:
    """Return the SEC-required ten-digit CIK representation."""
    digits = "".join(character for character in str(cik) if character.isdigit())
    if not digits or len(digits) > 10:
        raise ValueError(f"Invalid CIK: {cik!r}")
    return digits.zfill(10)


def manager_name(manager_code: str) -> str:
    metadata = FUND_CONFIG[manager_code]
    return str(metadata.get("display_name") or metadata["name"])
