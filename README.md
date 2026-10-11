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

In the Streamlit app, open **Data & methodology**, expand **Refresh data from SEC EDGAR** and click
**Fetch latest EDGAR filings**. The UI checks for unseen accessions, rebuilds
only affected report periods, and preserves the existing historical files.
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

The sidebar separates Overview, Sector research, Asset changes, Sector changes,
Consensus & positioning, Strategy backtests, Holdings explorer, and Data & methodology.
Both sector charts share a quarter-range slider. Choose Duquesne, Appaloosa or
Thiel Macro within Strategy backtests. Holdings explorer supports quarter,
manager and ticker filters with CSV export. SEC refresh and sector mapping
controls live in Data & methodology.

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


## Repaired historical simulations

Rebuild all tested portfolio universes with an explicit, exclusive price cutoff:

```powershell
.venv/Scripts/python.exe scripts/build_backtests.py --start 2014-01-01 --end 2026-09-12 --sweep
```

For a previously downloaded complete snapshot, add `--reuse-prices-dir data/prices/repaired`.
The original event file is preserved; resolved events are written to
`data/processed/sec_holdings_events_resolved.csv`. Prior headline results and prices
are archived under their respective `pre_repair` directories.

- Original non-option holdings are ranked by CUSIP before ticker or price filters.
- Exact US CUSIP matches are used from the security master. Ambiguous issuer/foreign
  matches remain unresolved. Dated, sourced exceptions live in
  `data/historical_security_overrides.csv`; no acquiring-company return is substituted
  for a delisted target. Vendor adjustments and corporate-action metadata are retained.
- Full-universe mapping, selected-value mapping, and executable-value coverage are
  reported separately. Trading requires 90% coverage of the original selected value.
  Missing allocations remain cash; an event below the gate liquidates to cash.
- Older-report amendments cannot replace newer disclosed portfolios. Empty non-option
  books explicitly target cash.
- Missing/nonpositive held prices or ten unchanged closes invalidate a simulation.
  Prices are never forward-filled, and missing delisting proceeds are never invented.
- Strategy and benchmark share one entry timestamp. Next-open simulations require
  adjusted benchmark opens. SPY/QQQ also remain available as portfolio holdings.
- The headline rules remain top 10, next close, 63 sessions, and 10 bps of gross
  turnover; sensitivity results are not ranked to hit a desired return.

`simulation_policy.json` locks the trading rules. Changing trading rules requires a
separate output directory. Charts, statistics and scenario sweeps use one continuous
period from the earliest common availability across all three strategy funds to their
latest shared observation. Existing positions carry into the period, and NAV is rebased
using only returns within that period. There is no development/test split.
Historical simulations are neither the managers' actual returns nor forecasts.

The build writes SPY/QQQ comparisons, per-event coverage, evaluation CSVs, validity
status files, and an input-hash manifest. The dashboard refuses to display old results
as valid when a rebuilt simulation fails. Unresolved securities and failed downloads
remain visible in diagnostic files; a survivorship-free historical data vendor may be
needed to recover retired securities.
