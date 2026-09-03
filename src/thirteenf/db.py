from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


DEFAULT_DB_PATH = Path("data") / "alpha.db"


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> Path:
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(target) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS filings (
                accession_number TEXT PRIMARY KEY,
                manager_code TEXT NOT NULL,
                cik TEXT NOT NULL,
                form TEXT NOT NULL,
                report_period TEXT NOT NULL,
                filing_date TEXT NOT NULL,
                acceptance_datetime TEXT NOT NULL,
                amendment_type TEXT,
                source_url TEXT NOT NULL,
                content_hash TEXT
            );
            CREATE TABLE IF NOT EXISTS holdings (
                accession_number TEXT NOT NULL REFERENCES filings(accession_number),
                cusip TEXT NOT NULL,
                figi TEXT NOT NULL DEFAULT '',
                put_call TEXT NOT NULL DEFAULT '',
                investment_discretion TEXT NOT NULL DEFAULT '',
                other_manager TEXT NOT NULL DEFAULT '',
                issuer TEXT,
                title_of_class TEXT,
                market_value_usd REAL NOT NULL,
                shares REAL,
                portfolio_weight REAL,
                ticker TEXT,
                sector TEXT,
                PRIMARY KEY (accession_number, cusip, figi, put_call, investment_discretion, other_manager)
            );
            CREATE TABLE IF NOT EXISTS quarterly_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quarter TEXT NOT NULL,
                ticker_clean TEXT NOT NULL,
                fund TEXT NOT NULL,
                portfolio_weight REAL,
                source TEXT,
                company TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (quarter, ticker_clean, fund, source)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_quarterly_snapshot
                ON quarterly_snapshots(quarter, ticker_clean, fund, source);
            """
        )
    return target


def insert_snapshot(db_path: str | Path, quarter: str, rows: Iterable[dict]) -> None:
    records = [
        (
            quarter, row.get("ticker_clean") or row.get("ticker") or "",
            row.get("fund") or "", float(row.get("portfolio_weight", row.get("pct_portfolio", 0.0)) or 0.0),
            row.get("source") or "", row.get("company") or row.get("issuer") or "",
        )
        for row in rows
    ]
    with sqlite3.connect(Path(db_path)) as conn:
        conn.executemany(
            """
            INSERT INTO quarterly_snapshots
                (quarter, ticker_clean, fund, portfolio_weight, source, company)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(quarter, ticker_clean, fund, source) DO UPDATE SET
                portfolio_weight=excluded.portfolio_weight,
                company=excluded.company,
                created_at=CURRENT_TIMESTAMP
            """,
            records,
        )


def upsert_filing(db_path: str | Path, filing: dict, holdings: Iterable[dict]) -> None:
    """Atomically persist one filing and its canonical holding rows."""
    init_db(db_path)
    with sqlite3.connect(Path(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO filings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(accession_number) DO UPDATE SET
                amendment_type=excluded.amendment_type,
                content_hash=excluded.content_hash
            """,
            tuple(filing.get(key, "") for key in (
                "accession_number", "manager_code", "cik", "form", "report_period",
                "filing_date", "acceptance_datetime", "amendment_type", "source_url", "content_hash",
            )),
        )
        conn.executemany(
            """
            INSERT INTO holdings
                (accession_number, cusip, figi, put_call, investment_discretion, other_manager,
                 issuer, title_of_class, market_value_usd, shares,
                 portfolio_weight, ticker, sector)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(accession_number, cusip, figi, put_call, investment_discretion, other_manager)
            DO UPDATE SET market_value_usd=excluded.market_value_usd,
                          shares=excluded.shares,
                          portfolio_weight=excluded.portfolio_weight,
                          ticker=excluded.ticker,
                          sector=excluded.sector
            """,
            [tuple(row.get(key, "") for key in (
                "accession_number", "cusip", "figi", "put_call", "investment_discretion", "other_manager",
                "issuer", "title_of_class", "market_value_usd", "shares",
                "portfolio_weight", "ticker", "sector",
            )) for row in holdings],
        )
