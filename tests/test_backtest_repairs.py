import numpy as np
import pandas as pd
import pytest

from thirteenf.backtest import (StrategySpec, PriceDataError, build_disclosed_book_signals,
    filter_signals_for_price_coverage, run_event_backtest, run_strategy_comparison,
    full_period_comparison, performance_summary)
from thirteenf.security_history import resolve_historical_holdings


def event(ticker="A", value=100, accession="one", available="2026-01-02T20:00:00Z", period="2025-12-31", cusip="000000001"):
    return dict(manager_code="DUQ", snapshot_accession=accession, available_at=available,
                report_period=period, ticker_clean=ticker, market_value_usd=value,
                put_call="", cusip=cusip, sector="Technology")


def prices():
    return pd.DataFrame({"A":[100.,100.,110.,121.]}, index=pd.bdate_range("2026-01-02",periods=4))


def test_rank_original_securities_before_mapping_and_preserve_cash():
    e=pd.DataFrame([event(None,60,cusip="missing"),event("A",40)])
    signals=build_disclosed_book_signals(e,StrategySpec("DUQ",top_n=1))
    assert signals.ticker_clean.isna().all()
    assert signals.target_weight.iloc[0]==1
    signals=build_disclosed_book_signals(e,StrategySpec("DUQ",top_n=2))
    p=prices()
    selected,coverage=filter_signals_for_price_coverage(signals,p,minimum_coverage=.4)
    assert coverage.mapping_coverage.iloc[0]==pytest.approx(.4)
    assert coverage.weight_coverage.iloc[0]==pytest.approx(.4)
    assert selected.target_weight.sum()==pytest.approx(.4)
    result=run_event_backtest(selected,p,pd.Series(100.,index=p.index),transaction_cost_bps=0)
    assert result.strategy_nav.iloc[-1]==pytest.approx(1+.4*.21)


def test_low_coverage_rebalance_liquidates_instead_of_retaining_previous_positions():
    e=pd.DataFrame([event(),event(None,100,"two","2026-01-05T20:00:00Z","2026-03-31","missing")])
    p=prices()
    result,coverage=run_strategy_comparison(e,p,pd.Series(100.,index=p.index),StrategySpec("DUQ",transaction_cost_bps=0))
    assert coverage.status.iloc[-1]=="rejected_low_coverage"
    assert result.disclosed_nav.iloc[-1]==pytest.approx(1.1)
    assert result.disclosed_exposure.iloc[-1]==0


def test_zero_equity_new_filing_targets_cash():
    first=event(); empty=event(None,0,"two","2026-01-05T20:00:00Z","2026-03-31")
    p=prices()
    result,cov=run_strategy_comparison(pd.DataFrame([first,empty]),p,pd.Series(100.,index=p.index),StrategySpec("DUQ",transaction_cost_bps=0))
    assert cov.status.iloc[-1]=="empty_book"
    assert result.disclosed_nav.iloc[-1]==pytest.approx(1.1)


def test_old_amendment_does_not_replace_newer_portfolio():
    rows=[event(),event(None,100,"old-amendment","2026-01-05T20:00:00Z","2025-06-30","missing")]
    p=prices()
    result,cov=run_strategy_comparison(pd.DataFrame(rows),p,pd.Series(100.,index=p.index),StrategySpec("DUQ",transaction_cost_bps=0))
    assert cov.status.iloc[-1]=="stale_report_ignored"
    assert result.disclosed_nav.iloc[-1]==pytest.approx(1.21)


def test_identical_asset_and_benchmark_match_at_next_open():
    p=prices(); opening=p.copy(); opening.iloc[1,0]=90
    result,_=run_strategy_comparison(pd.DataFrame([event()]),p,p.A,StrategySpec("DUQ",execution_timing="next_open",transaction_cost_bps=0),open_prices=opening,benchmark_open_prices=opening.A)
    np.testing.assert_allclose(result.disclosed_nav,result.benchmark_nav)
    np.testing.assert_allclose((1+result.benchmark_return).cumprod(),result.benchmark_nav)


def test_next_open_filter_does_not_use_future_close():
    p=prices(); opening=p.copy();p.iloc[1,0]=np.nan
    s=build_disclosed_book_signals(pd.DataFrame([event()]),StrategySpec("DUQ"))
    filtered,cov=filter_signals_for_price_coverage(s,p,execution_timing="next_open",open_prices=opening)
    assert cov.status.iloc[0]=="accepted"
    with pytest.raises(PriceDataError):
        run_event_backtest(filtered,p,pd.Series(100.,index=p.index),execution_timing="next_open",open_prices=opening,benchmark_open_prices=pd.Series(100.,index=p.index))


def test_missing_held_price_rejects_instead_of_creating_cash():
    p=prices();p.iloc[2,0]=np.nan
    with pytest.raises(PriceDataError,match="held-security"):
        run_strategy_comparison(pd.DataFrame([event()]),p,pd.Series(100.,index=p.index),StrategySpec("DUQ"))


def test_missing_benchmark_price_is_not_forward_filled():
    p=prices();benchmark=pd.Series(100.,index=p.index);benchmark.iloc[2]=np.nan
    with pytest.raises(PriceDataError,match="benchmark"):
        run_strategy_comparison(pd.DataFrame([event()]),p,benchmark,StrategySpec("DUQ"))


def test_stale_prices_require_review():
    p=pd.DataFrame({"A":100.},index=pd.bdate_range("2026-01-02",periods=15))
    with pytest.raises(PriceDataError,match="unchanged closes"):
        run_strategy_comparison(pd.DataFrame([event()]),p,p.A,StrategySpec("DUQ"))


def test_master_resolution_rejects_issuer_guesses_and_foreign_listings():
    e=pd.DataFrame([event(None)])
    master=pd.DataFrame([dict(cusip="000000001",ticker="A",match_method="cusip_search",classification_source="test")])
    assert resolve_historical_holdings(e,master).ticker_clean.iloc[0]=="A"
    master.loc[0,"ticker"]="A.MU"
    assert resolve_historical_holdings(e,master).ticker_clean.isna().all()
    master.loc[0,"ticker"]="A";master.loc[0,"match_method"]="issuer_search_review"
    assert resolve_historical_holdings(e,master).ticker_clean.isna().all()


def test_dated_override_cannot_leak_beyond_valid_period():
    e=pd.DataFrame([event(None,period="2014-03-31"),event(None,period="2025-12-31")])
    override=pd.DataFrame([dict(cusip="000000001",ticker="A",valid_from="2014-01-01",valid_to="2015-12-31",source_url="https://example.com/source",note="test")])
    result=resolve_historical_holdings(e,pd.DataFrame(),override)
    assert result.ticker_clean.iloc[0]=="A"
    assert pd.isna(result.ticker_clean.iloc[1])


def test_common_period_metrics_rebase_each_return_series():
    dates=pd.date_range("2020-12-29",periods=6)
    c=pd.DataFrame({"date":dates})
    for name in ["disclosed","sector_balanced","benchmark"]:
        c[f"{name}_return"]=[0,.1,.1,.1,.1,.1]
        c[f"{name}_nav"]=(1+c[f"{name}_return"]).cumprod()
    result=performance_summary(full_period_comparison(c, dates[3], dates[-1]))
    assert len(result)==3
    assert result.total_return.iloc[0]==pytest.approx(1.1**3-1)
