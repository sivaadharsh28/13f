from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd

from thirteenf.config import PROCESSED_DATA_DIR, RAW_DATA_DIR, SEC_USER_AGENT_ENV
from thirteenf.demo_data import get_demo_snapshot
from thirteenf.funds import FUND_CONFIG, normalize_cik
from thirteenf.ingest import prepare_holdings_dataframe
from thirteenf.scrapers.dataroma import scrape_dataroma
from thirteenf.scrapers.sec_edgar import parse_13f_cover_xml, parse_13f_xml_content
from thirteenf.sec_live import (
    SECClient,
    fetch_sec_company_filings,
    parse_filing_document_index,
    validate_manager_identity,
)
from thirteenf.sec_pipeline import (
    attach_filing_metadata,
    build_as_of_snapshots,
    filing_value_unit,
    reconcile_amendments,
)
from thirteenf.sector import assign_sector, load_security_master
from thirteenf.storage import save_raw_artifact, save_snapshot


def _is_valid_ticker(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip().upper().replace(".", "")
    return bool(re.fullmatch(r"[A-Z0-9-]+", text)) and text not in {"≡", "—", "-"}


def rebuild_processed_snapshot(raw_dir: str | Path | None = None, output_path: str | Path | None = None) -> pd.DataFrame:
    """Build a cleaned processed snapshot from raw holdings files or fall back to demo data."""
    source_dir = Path(raw_dir) if raw_dir is not None else RAW_DATA_DIR
    target_path = Path(output_path) if output_path is not None else source_dir.parent / "processed" / "combined_holdings.csv"
    frames: list[pd.DataFrame] = []

    for csv_path in sorted(source_dir.glob("*_raw_holdings.csv")):
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            continue
        if df.empty:
            continue
        if "ticker" in df.columns:
            df = df[df["ticker"].map(_is_valid_ticker)].copy()
        if not df.empty:
            frames.append(prepare_holdings_dataframe(df))

    if frames:
        combined = pd.concat(frames, ignore_index=True)
    else:
        combined = get_demo_snapshot().copy()

    if "ticker" not in combined.columns and "ticker_clean" in combined.columns:
        combined["ticker"] = combined["ticker_clean"]
    if "source" not in combined.columns:
        combined["source"] = "demo"
    if "portfolio_weight" not in combined.columns and "pct_portfolio" in combined.columns:
        combined["portfolio_weight"] = combined["pct_portfolio"]

    target_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(target_path, index=False)
    return combined


def run_dataroma_ingestion(output_dir: str | Path | None = None) -> pd.DataFrame:
    """Fetch Dataroma holdings for all configured managers and save raw + processed snapshots."""
    target_dir = Path(output_dir) if output_dir else RAW_DATA_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    frames: list[pd.DataFrame] = []
    for fund_code, meta in FUND_CONFIG.items():
        if meta["source"] != "dataroma":
            continue

        df = scrape_dataroma(meta["fund_code"], meta["name"])
        if df.empty:
            continue

        df["source"] = "dataroma"
        df["fund_code"] = fund_code
        raw_path = target_dir / f"{fund_code.lower()}_raw_holdings.csv"
        df.to_csv(raw_path, index=False)
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    processed = prepare_holdings_dataframe(combined)
    processed_path = target_dir.parent / "processed" / "combined_holdings.csv"
    processed_path.parent.mkdir(parents=True, exist_ok=True)
    processed.to_csv(processed_path, index=False)
    return processed


def _selected_periods(filings: pd.DataFrame, quarters: int | None, start_date: str | None) -> pd.DataFrame:
    selected = filings.copy()
    if start_date:
        report_dates = pd.to_datetime(selected["report_period"], errors="coerce")
        selected = selected[report_dates.ge(pd.Timestamp(start_date))]
    selected = selected.sort_values("acceptance_datetime", ascending=False)
    if quarters is not None:
        periods = selected["report_period"].drop_duplicates().head(quarters)
        selected = selected[selected["report_period"].isin(periods)]
    return selected.sort_values("acceptance_datetime").reset_index(drop=True)


def fetch_manager_holdings(
    manager_code: str,
    client: SECClient,
    quarters: int | None = 8,
    raw_dir: str | Path | None = None,
    start_date: str | None = None,
) -> pd.DataFrame:
    """Fetch and normalize SEC 13F holdings for one configured manager."""
    metadata = FUND_CONFIG[manager_code]
    if metadata.get("source") != "sec":
        return pd.DataFrame()

    cik = normalize_cik(metadata["cik"])
    filings = fetch_sec_company_filings(
        cik,
        count=None if start_date else quarters,
        client=client,
        start_date=start_date,
    )
    if filings.empty:
        return pd.DataFrame()
    validate_manager_identity(str(filings.iloc[0]["entity_name"]), list(metadata.get("aliases", [])))
    selected = _selected_periods(filings, quarters=quarters, start_date=start_date)

    target_root = Path(raw_dir) if raw_dir is not None else RAW_DATA_DIR / "sec"
    frames: list[pd.DataFrame] = []
    for filing in selected.to_dict("records"):
        index_html = client.get_text(str(filing["index_url"]))
        documents = parse_filing_document_index(index_html, str(filing["index_url"]))
        cover_url = documents.get("cover_xml_url") or str(filing.get("primary_document") or "")
        info_url = documents.get("information_table_xml_url", "")
        if not info_url:
            raise ValueError(f"Cannot locate information table for {filing['accession_number']}")

        accession_dir = target_root / manager_code / str(filing["accession_number"])
        cover_bytes = client.get_bytes(cover_url) if cover_url else b""
        info_bytes = client.get_bytes(info_url)
        if cover_bytes:
            save_raw_artifact(cover_bytes, accession_dir, "cover.xml")
            cover = parse_13f_cover_xml(cover_bytes)
        else:
            cover = {"amendment_type": ""}
        _, content_hash = save_raw_artifact(info_bytes, accession_dir, "information_table.xml")

        amendment_type = str(cover.get("amendment_type") or "")
        if filing["form"] == "13F-HR/A" and not amendment_type:
            raise ValueError(f"Cannot determine amendment type for {filing['accession_number']}")
        filing["content_hash"] = content_hash
        holdings = parse_13f_xml_content(info_bytes, value_unit=filing_value_unit(str(filing["filing_date"])))
        if holdings.empty:
            continue
        frames.append(attach_filing_metadata(holdings, filing, manager_code, info_url, amendment_type))

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def run_sec_ingestion(
    output_dir: str | Path | None = None,
    quarters: int | None = 8,
    user_agent: str | None = None,
    start_date: str | None = None,
) -> pd.DataFrame:
    """Fetch configured SEC managers and save reconciled history plus event snapshots."""
    client = SECClient(user_agent or os.getenv(SEC_USER_AGENT_ENV, ""))
    target_dir = Path(output_dir) if output_dir else PROCESSED_DATA_DIR
    frames: list[pd.DataFrame] = []
    for code, metadata in FUND_CONFIG.items():
        if metadata.get("source") != "sec":
            continue
        try:
            frame = fetch_manager_holdings(code, client, quarters=quarters, start_date=start_date)
        except Exception as exc:
            raise RuntimeError(f"{code}: {type(exc).__name__}: {exc}") from exc
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    events = build_as_of_snapshots(combined)
    history = reconcile_amendments(combined)
    master_path = Path("data/security_master.csv")
    if master_path.exists():
        master = load_security_master(master_path)
        events = assign_sector(events, security_master=master)
        history = assign_sector(history, security_master=master)
    save_snapshot(events, target_dir / "sec_holdings_events.csv")
    save_snapshot(history, target_dir / "sec_holdings_history.csv")
    return history


def build_live_snapshot() -> pd.DataFrame:
    """Attempt to build a live snapshot from the configured sources."""
    frames: list[pd.DataFrame] = []

    dataroma_df = run_dataroma_ingestion(output_dir=RAW_DATA_DIR)
    if not dataroma_df.empty:
        frames.append(dataroma_df)

    # SEC EDGAR is the primary live source for Duquesne when available.
    # This path is intentionally kept separate so the dashboard can distinguish.
    sec_path = RAW_DATA_DIR.parent / "processed" / "duquesne_live.csv"
    if sec_path.exists():
        sec_df = pd.read_csv(sec_path)
        if not sec_df.empty:
            frames.append(sec_df)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def write_fund_config() -> str:
    """Write the configured funds metadata to JSON for documentation and monitoring."""
    path = RAW_DATA_DIR.parent / "fund_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(FUND_CONFIG, fh, indent=2, sort_keys=True)
    return str(path)
