"""Resolve the current SEC holdings universe into a reviewable security master.

Yahoo Finance's public search results accept CUSIPs and return the matched
exchange symbol plus its commonly used sector label.  Results are normalized
to the project's GICS-style sector names and retain provenance for auditing.
This is a research-data helper, not a trading-time dependency.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
import requests


SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
SECTOR_NAMES = {
    "Basic Materials": "Materials",
    "Communication Services": "Communication Services",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Energy": "Energy",
    "Financial Services": "Financials",
    "Healthcare": "Health Care",
    "Industrials": "Industrials",
    "Real Estate": "Real Estate",
    "Technology": "Information Technology",
    "Utilities": "Utilities",
}

# Reviewed exceptions cover retired securities, CUSIPs whose Yahoo result
# prefers a foreign listing, and funds for which issuer-level GICS is not an
# honest description of the exposure.  Symbols are the US-traded/historical
# symbols corresponding to the 13F security.
REVIEWED_OVERRIDES = {
    "000000000": {"ticker": "", "sector": "Unknown", "matched_name": "Unidentified 13F placeholder"},
    "02079K305": {"ticker": "GOOGL"},
    "03940C100": {"ticker": "ACLX", "sector": "Health Care", "matched_name": "Arcellx, Inc."},
    "04351P101": {"ticker": "ASND"},
    "056752108": {"ticker": "BIDU"},
    "11271J107": {"ticker": "BN"},
    "136375102": {"ticker": "CNI"},
    "13646K108": {"ticker": "CP"},
    "15101Q207": {"ticker": "CLS"},
    "165167172": {"ticker": "EXE-WT"},
    "165167180": {"ticker": "EXE-WT"},
    "171757206": {"ticker": "CDTX", "sector": "Health Care", "matched_name": "Cidara Therapeutics, Inc."},
    "200340107": {"ticker": "CMA", "sector": "Financials", "matched_name": "Comerica Incorporated"},
    "23918K108": {"ticker": "DVA"},
    "254709108": {"ticker": "DFS", "sector": "Financials", "matched_name": "Discover Financial Services"},
    "29109X106": {"ticker": "AZPN", "sector": "Information Technology", "matched_name": "Aspen Technology, Inc."},
    "372460105": {"ticker": "GPC"},
    "37950E259": {"sector": "Country/Regional Equity ETF"},
    "44267T102": {"ticker": "HHH"},
    "46137V357": {"sector": "Diversified Equity ETF"},
    "464286400": {"sector": "Country/Regional Equity ETF"},
    "464286772": {"sector": "Country/Regional Equity ETF"},
    "464287184": {"sector": "Country/Regional Equity ETF"},
    "464287234": {"sector": "Country/Regional Equity ETF"},
    "464287655": {"sector": "Diversified Equity ETF"},
    "46428R107": {"sector": "Commodities"},
    "47215P106": {"ticker": "JD"},
    "500767306": {"sector": "Thematic Equity ETF"},
    "512807108": {"ticker": "LRCX"},
    "531229722": {"ticker": "LLYVK", "sector": "Communication Services", "matched_name": "Liberty Media Corporation Series C Liberty Live"},
    "531229854": {"ticker": "FWONK", "sector": "Communication Services", "matched_name": "Liberty Formula One Series C"},
    "722304102": {"ticker": "PDD"},
    "78462F103": {"sector": "Diversified Equity ETF"},
    "78464A698": {"sector": "Financials"},
    "78464A797": {"sector": "Financials"},
    "78468R796": {"sector": "Diversified Equity ETF"},
    "812215101": {"ticker": "SEG-RT", "sector": "Real Estate", "matched_name": "Seaport Entertainment Group rights"},
    "81369Y605": {"sector": "Financials"},
    "81686C104": {"ticker": "SEMR", "sector": "Information Technology", "matched_name": "Semrush Holdings, Inc."},
    "82686Q101": {"ticker": "SLN"},
    "830566105": {"ticker": "SKX", "sector": "Consumer Discretionary", "matched_name": "Skechers U.S.A., Inc."},
    "83056P715": {"ticker": "SKE"},
    "83200N103": {"ticker": "SMAR", "sector": "Information Technology", "matched_name": "Smartsheet Inc."},
    "845467109": {"ticker": "SWN", "sector": "Energy", "matched_name": "Southwestern Energy Company"},
    "85205L107": {"ticker": "SWTX", "sector": "Health Care", "matched_name": "SpringWorks Therapeutics, Inc."},
    "867975104": {"ticker": "SNRE", "sector": "Communication Services", "matched_name": "Sunrise Communications AG ADS"},
    "874039100": {"ticker": "TSM"},
    "87807B107": {"ticker": "TRP"},
    "878742204": {"ticker": "TECK"},
    "88034P109": {"ticker": "TME"},
    "912909108": {"ticker": "X", "sector": "Materials", "matched_name": "United States Steel Corporation"},
    "92189F676": {"sector": "Information Technology"},
    "922908363": {"sector": "Diversified Equity ETF"},
    "925050106": {"ticker": "VRNA", "sector": "Health Care", "matched_name": "Verona Pharma plc"},
    "D18190898": {"ticker": "DB"},
    "M3760D101": {"ticker": "ESLT"},
    "N3168P101": {"ticker": "FER"},
    "Y2573F102": {"ticker": "FLEX"},
}


def _representative_universe(holdings: pd.DataFrame) -> pd.DataFrame:
    columns = ["cusip", "issuer", "title_of_class"]
    rows = holdings[columns].fillna("").copy()
    rows["cusip"] = rows["cusip"].astype(str).str.strip().str.zfill(9)
    rows = rows[rows["cusip"].str.len().eq(9)]
    # Prefer the most frequently observed spelling for each security.
    counts = rows.value_counts(columns).rename("observations").reset_index()
    return (
        counts.sort_values(["cusip", "observations"], ascending=[True, False])
        .drop_duplicates("cusip")
        .sort_values("cusip")
        .reset_index(drop=True)
    )


def _search(session: requests.Session, query: str, retries: int = 3) -> list[dict]:
    for attempt in range(retries):
        response = session.get(
            SEARCH_URL,
            params={"q": query, "quotesCount": 8, "newsCount": 0},
            timeout=20,
        )
        if response.status_code == 200:
            return response.json().get("quotes", [])
        if response.status_code not in {429, 500, 502, 503, 504}:
            response.raise_for_status()
        time.sleep(2 ** attempt)
    response.raise_for_status()
    return []


def _candidate_score(candidate: dict, issuer: str) -> float:
    name = str(candidate.get("longname") or candidate.get("shortname") or "")
    similarity = SequenceMatcher(None, issuer.upper(), name.upper()).ratio()
    type_bonus = 1 if candidate.get("quoteType") in {"EQUITY", "ETF"} else 0
    return type_bonus + similarity


def _resolve_one(session: requests.Session, cusip: str, issuer: str) -> dict[str, str]:
    candidates = _search(session, cusip)
    method = "cusip_search"
    if not candidates:
        candidates = _search(session, issuer)
        method = "issuer_search_review"
    if not candidates:
        return {
            "ticker": "", "sector": "Unknown", "raw_sector": "",
            "quote_type": "", "matched_name": "", "match_method": "unresolved",
        }
    candidate = max(candidates, key=lambda item: _candidate_score(item, issuer))
    quote_type = str(candidate.get("quoteType", ""))
    raw_sector = str(candidate.get("sector", ""))
    if raw_sector in SECTOR_NAMES:
        sector = SECTOR_NAMES[raw_sector]
    elif quote_type == "ETF":
        sector = "Exchange-Traded Fund"
    elif quote_type in {"MUTUALFUND", "INDEX"}:
        sector = "Fund/Index"
    else:
        sector = "Unknown"
    return {
        "ticker": str(candidate.get("symbol", "")),
        "sector": sector,
        "raw_sector": raw_sector,
        "quote_type": quote_type,
        "matched_name": str(candidate.get("longname") or candidate.get("shortname") or ""),
        "match_method": method,
    }


def build_security_master(holdings_path: str | Path, delay: float = 0.08) -> pd.DataFrame:
    holdings = pd.read_csv(holdings_path, dtype=str, keep_default_na=False)
    universe = _representative_universe(holdings)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 thirteenf-research/1.0"})
    resolved: list[dict[str, str]] = []
    for row in universe.itertuples(index=False):
        match = _resolve_one(session, row.cusip, row.issuer)
        resolved.append({
            "cusip": row.cusip,
            **match,
            "issuer": row.issuer,
            "title_of_class": row.title_of_class,
            "valid_from": "",
            "valid_to": "",
            "classification_source": "Yahoo Finance search",
            "retrieved_at": date.today().isoformat(),
        })
        time.sleep(delay)
    return apply_reviewed_overrides(pd.DataFrame(resolved))


def apply_reviewed_overrides(master: pd.DataFrame) -> pd.DataFrame:
    result = master.copy()
    for cusip, values in REVIEWED_OVERRIDES.items():
        selected = result["cusip"].eq(cusip)
        if not selected.any():
            continue
        for column, value in values.items():
            result.loc[selected, column] = value
        result.loc[selected, "match_method"] = "reviewed_override"
        result.loc[selected, "classification_source"] = (
            "Manual review: SEC/Nasdaq/issuer; Yahoo Finance sector taxonomy"
        )
    return result


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdings", default="data/processed/sec_holdings_history.csv")
    parser.add_argument("--candidate", help="Apply reviewed overrides to an existing candidate CSV")
    parser.add_argument("--output", default="-")
    parser.add_argument("--delay", type=float, default=0.08)
    args = parser.parse_args()
    master = (
        apply_reviewed_overrides(pd.read_csv(args.candidate, dtype=str, keep_default_na=False))
        if args.candidate else build_security_master(args.holdings, args.delay)
    )
    if args.output == "-":
        master.to_csv(sys.stdout, index=False)
    else:
        master.to_csv(args.output, index=False)


if __name__ == "__main__":
    main()
