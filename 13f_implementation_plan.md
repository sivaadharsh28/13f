# SEC-First 13F Research Platform – Implementation Plan

## Scope and limitations

The platform studies public Form 13F disclosures. Results describe the
reported 13F book, not a manager's complete portfolio. Short positions, cash,
many foreign securities and other non-13(f) assets are absent. Put/call rows
are stored separately and excluded from long-only replication by default.

## 1. Canonical manager registry

`src/thirteenf/funds.py` is the source of truth. Every CIK must be ten digits
and must be validated against the entity name returned by the SEC before any
filing is accepted. The observed universe includes Pershing Square, Valley
Forge, Appaloosa, Akre, Berkshire, Himalaya, TCI, Dorsey, Duquesne and Thiel
Macro.

## 2. SEC EDGAR ingestion

1. Query `data.sec.gov/submissions/CIK##########.json`.
2. Retain `13F-HR` and `13F-HR/A`, including accession, report date, filing
   date and acceptance timestamp.
3. Resolve the filing document index and select the document whose type is
   `INFORMATION TABLE`; never select XML by filename heuristics.
4. Store raw cover and information-table XML immutably with SHA-256 provenance.
5. Parse XML namespace-independently and retain CUSIP, optional FIGI, issuer,
   class, value, shares/principal, put/call, discretion and voting fields.
6. Treat filings before 2023-01-03 as values in thousands of dollars and newer
   filings as values in dollars. Preserve both raw value and unit.
7. Reconcile restatements as replacements and `adds new holdings` amendments
   as additions. Materialize each public disclosure state for backtesting.
8. Require a declared organization/contact user-agent and throttle below the
   SEC's published ten-request-per-second ceiling.

## 3. Identifier and sector enrichment

SEC data remains authoritative for positions and values. A versioned local
security master maps CUSIP/FIGI to ticker and GICS sector using `valid_from`
and `valid_to` dates. Unresolved holdings remain visible as `Unknown`; they are
never silently discarded or assigned synthetic sectors. Dataroma is a
secondary validation/fallback source and must retain its page portfolio date.

## 4. Storage and quality controls

Store filings by accession and holdings by accession/security/option type/
discretion. Ingestion is idempotent. Reject manager identity mismatches,
unknown amendment semantics, changed raw artifacts and demo rows in production.
Track unmapped value percentage, weight totals, row totals and failures.

## 5. Sector rotation

Compute weights within each reconciled `manager × report_period` book, then
aggregate by `manager × quarter × sector`. The chart uses quarter on X and
portfolio weight on Y, with a manager selector. Common equity, ETFs and options
must be separable; the dashboard warns about unmapped weight.

## 6. Signals and backtesting

The first registered strategies are disclosed-book variants for Duquesne,
Appaloosa and Thiel Macro:

- top ten common-equity positions by disclosed market value;
- proportional weights normalized to 100%;
- signal availability at SEC acceptance time;
- execution at the next available session close after disclosure;
- maximum holding period of 63 trading sessions or the next disclosure;
- 10 bps one-way costs, with 0 and 25 bps sensitivity runs;
- SPY buy-and-hold benchmark;
- equal-capital-per-represented-sector baseline.

No signal may use `report_period` as its availability date. Amendments create a
new event and never rewrite an earlier event snapshot.

## 7. Dashboard and operations

The dashboard reads persisted SEC output and performs no automatic network
requests. Refresh is explicit. Demo mode is explicit and separate. Display the
data source, latest acceptance time, unmapped weight and ingestion errors.

## 8. Verification gates

- Realistic namespaced XML fixtures, including current and legacy value units.
- CIK/entity identity assertions for all managers.
- Amendment replacement/addition tests.
- Current Dataroma layout fixture.
- Cross-quarter isolation and per-manager sector aggregation tests.
- Next-session execution, holding expiry and transaction-cost tests.
- Idempotent persistence tests.
