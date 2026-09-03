# 13F Disclosed-Book Research

An SEC-first Python pipeline for collecting public Form 13F filings, computing
manager-level sector rotation and testing point-in-time disclosed-book
strategies without quarter-end look-ahead.

Form 13F is delayed and incomplete: it does not disclose short positions,
cash, many foreign holdings or a manager's full macro exposure.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
$env:THIRTEENF_SEC_USER_AGENT = "Your Organization research@example.com"
```

The SEC requires automated clients to identify an organization and contact.

## Ingest

```powershell
thirteenf --source sec --start-year 2014
thirteenf --source sec --quarters 8
thirteenf --source sec --manager DUQ --manager AM --manager THIEL
```

Raw SEC documents are stored under `data/raw/sec/`. Reconciled history is
written to `data/processed/sec_holdings_history.csv`; point-in-time amendment
events are written to `data/processed/sec_holdings_events.csv`.

Dataroma is an explicit fallback/validation source:

```powershell
thirteenf --source dataroma
```

## Security master

SEC 13F tables provide CUSIP and optional FIGI, not exchange tickers. The
reviewed `data/security_master.csv` maps the current holdings universe to US
symbols and normalized sector names. It retains the web match, method, source,
and retrieval date so overrides remain auditable. Broad, country, thematic,
and commodity ETFs are kept separate; sector ETFs use their represented
sector. Unidentified zero-value SEC placeholders remain `Unknown`.

To refresh a candidate from the latest holdings universe for manual review:

```powershell
python scripts/build_security_master.py --output data/security_master.candidate.csv
```

The helper uses Yahoo Finance's public CUSIP search for candidate symbols and
sector labels, then applies reviewed SEC/Nasdaq/issuer-based exceptions.

## Dashboard and tests

```powershell
streamlit run streamlit_app.py
pytest -q
```

Both sector charts share an interactive quarter-range slider. The app also
contains separate Duquesne, Appaloosa, and Thiel Macro backtest sections.

## Backtest

Provide survivorship-aware adjusted-close CSVs rather than downloading today's
universe retrospectively. The price file uses a date index and one column per
ticker; the benchmark file uses a date index and one SPY adjusted-close column.

```powershell
thirteenf --backtest-manager DUQ `
  --events data/processed/sec_holdings_events.csv `
  --prices data/prices/adjusted_close.csv `
  --benchmark-prices data/prices/spy.csv `
  --output data/processed/backtest_duq.csv
```

Demo data is never used implicitly. It is available only with
`thirteenf --source demo`.
