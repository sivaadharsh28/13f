# Duquesne backtest audit

Audit date: 4 October 2026. Saved data covers 15 May 2014 through 11 September 2026.

## Conclusion

The saved 25.52% CAGR reproduces from the current code, but incomplete historical security mappings substantially change the portfolio being tested. It should not be used as an expected-return projection or represented as Duquesne's actual performance. Restoring historical holdings and prices is the first priority.

No production code or saved backtest result was changed during this audit.

## Findings, in priority order

### 1. Unmapped holdings disappear before portfolio selection

`src/thirteenf/backtest.py:85` removes missing ticker mappings before selecting the largest positions at line 95. About 45.1% of the non-option holding rows have no ticker. Across 52 events, the average fraction of non-option disclosed value with mappings is only 67.9%; the worst event is 12.7%.

Ranking the original holdings by CUSIP before checking prices gives executable coverage of the original top ten averaging 77.2%, with a minimum of 14.5%. The UI's 99.7% average and 95.1% minimum instead measure price coverage after missing mappings have already been discarded. These are different denominators; the latter hides the larger omission.

Missing original top-ten holdings include Google (37.6% of the original top-ten value in May 2014), SPDR Gold Trust (31.3% in August 2015), and historical Biogen, Halliburton, Netflix and AbbVie positions. These examples require historical identifier verification before mapping fixes.

A diagnostic that selects the original top ten, preserves executable weights, and leaves missing allocations as zero-return cash produces 19.40% CAGR, versus 25.52% currently. This is a sensitivity result, not a corrected return estimate or lower bound: missing assets could have gained or lost money. It changes both the selected holdings and the treatment of unavailable prices. Cash earns zero; executable trades still incur the same 10 bps cost. Missing securities' actual returns remain unknown.

### 2. Renormalization amplifies the surviving holdings

Selection and coverage filtering repeatedly scale the surviving positions to 100% (`backtest.py:99`, `:215`, `:325`). The replay reached roughly 59.9% META exposure on 28 January 2016 and 67.0% ILMN exposure on 20 January 2015. META contributed approximately 9.29 percentage points to the former day's portfolio return. These concentrations are properties of the reconstructed strategy, not evidence of the manager's actual portfolio exposure.

### 3. Benchmark and cost assumptions materially affect the comparison

On the headline period, SPY returned 13.97% CAGR and QQQ 19.52%. QQQ is a useful additional growth-equity comparator, not proof that all exposures or risk have been matched. Headline strategy annualized volatility was 25.40%, versus SPY's 17.28%; maximum drawdown was -39.07%, versus -33.72%.

| Scenario | Strategy CAGR | Benchmark CAGR |
| --- | ---: | ---: |
| Current top ten, SPY | 25.52% | 13.97% |
| Full mapped book | 24.55% | 13.97% |
| Top ten, 100 bps per unit of turnover | 20.49% | 13.97% |
| Top ten, five-session execution delay | 23.77% | 13.89% |
| Current top ten, QQQ | 25.52% | 19.52% |
| Ignore amendments to older report periods | 25.91% | 13.97% |
| Original top ten, missing allocations held in cash | 19.40% | 13.97% |

The delayed scenario starts 22 May 2014; the others start 15 May. All end 11 September 2026. Scenarios are separate sensitivities, not additive corrections. Full mapped book still excludes unmapped holdings and lacks a dedicated complete-universe price download: `scripts/build_backtests.py:29` downloads symbols from default top-ten strategies, so it does not guarantee full-book coverage.

### 4. Old amendments can replace a newer portfolio

Two amendment events on 17 November 2021 refer to March and June 2021. The current event engine allows the later June amendment to replace the already disclosed September portfolio. Ignoring both stale-report events raises CAGR to 25.91%, so this is a confirmed chronology defect but does not explain inflated headline performance in this sample.

### 5. Next-open benchmark starts at the wrong point

`backtest.py:401` rebases benchmark NAV to the first execution day's close even when the strategy enters at that day's open. A reproduction with an identical asset and benchmark, both moving from 100 at entry to 110 at close, reports strategy NAV 1.10 versus benchmark NAV 1.00. This affects next-open scenario comparisons, not the headline next-close result. Both should use the same executable entry time and adjusted benchmark opens where needed.

### 6. Missing prices silently turn a holding into cash

At `backtest.py:177` an unavailable return becomes zero, and at `:250` the corresponding position weight is removed without reducing NAV. A reproduction with prices 100, 100, missing keeps NAV at 1.00 while exposure falls from 100% to zero. This effectively assumes recovery at the previous valuation, which is unsupported without a corporate-action or liquidation record. There were no such held-position price dropouts in the replay of the current headline Duquesne run; this is a latent defect, not a measured cause of its returns.

### 7. Scenario selection is not validation

`app.py:477` ranks scenarios by proximity to a user-entered target CAGR. This picks assumptions using the same historical outcome being evaluated. It cannot establish that a projection is realistic. The coverage filter also restores all scenarios when none pass (`app.py:456`), and current coverage ignores unmapped holdings. Use fixed assumptions and an untouched evaluation period or a walk-forward evaluation instead.

## Checks that passed and limits

- Recomputed saved NAV agrees within 1e-13; an independent next-close replay reaches the same terminal value of 16.473064.
- Default signals enter after SEC acceptance, with next-close returns starting after entry. No quarter-end execution look-ahead was found in that default path.
- The default engine allows holdings to drift between filing rebalances; it does not implicitly rebalance daily.
- Twelve existing backtest and market-data tests passed. They do not cover all defects reproduced above.
- This audit uses saved vendor prices. It does not independently validate every price, historical ticker, corporate action, or filing against its original source.
- Form 13F omits short positions and has delayed reporting. A reconstructed long-only selection cannot establish the fund's actual total portfolio performance. SEC reference: https://www.sec.gov/files/divisions/investment/13ffaq.htm

## Recommended repair order

1. Resolve historical CUSIPs and corporate actions; rank the actual holdings before mapping/price filters, and show mapping plus executable-value coverage separately.
2. Require sufficient original-universe coverage; explicitly preserve unpriced allocations or reject the period. Avoid silently investing their capital in surviving securities.
3. Prevent older-report amendments from replacing newer portfolios; handle stale or missing prices explicitly.
4. Align strategy and benchmark entry timestamps, including benchmark open data for next-open simulations.
5. Rebuild prices for every tested universe, rerun the comparisons, and evaluate fixed assumptions out of sample. Present results as historical simulations.

## Reproduction and artifacts

Run `.venv/Scripts/python.exe reports/audit_duquesne.py` from the repository root. The script reads local files and writes only audit CSVs. Its residual-cash sensitivity isolates a copy of the engine with target renormalization disabled; it does not modify production functions.

- `duquesne_audit_scenarios.csv`: scenario results and dates.
- `duquesne_mapping_coverage.csv`: mapping and original-top-ten coverage per event.
- `duquesne_unpriced_original_top10.csv`: omitted original holdings.
- `duquesne_large_daily_contributions.csv`: single-security contributions above one percentage point in absolute value.
