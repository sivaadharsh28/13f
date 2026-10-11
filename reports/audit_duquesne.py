from pathlib import Path
from dataclasses import replace
import json
import inspect
import thirteenf.backtest as backtest_module
import numpy as np
import pandas as pd
from thirteenf.backtest import (STRATEGY_SPECS, build_disclosed_book_signals, filter_signals_for_price_coverage, run_strategy_comparison, run_event_backtest, performance_summary)

out = Path('reports')
events = pd.read_csv('data/processed/sec_holdings_events.csv', dtype={'cusip': str})
events = events[events.manager_code.eq('DUQ')].copy()
prices = pd.read_csv('data/prices/adjusted_close.csv', index_col=0, parse_dates=True)
opens = pd.read_csv('data/prices/adjusted_open.csv', index_col=0, parse_dates=True)
spy = pd.read_csv('data/prices/spy.csv', index_col=0, parse_dates=True).iloc[:,0]
qqq = pd.read_csv('data/prices/qqq.csv', index_col=0, parse_dates=True).iloc[:,0]
spec = STRATEGY_SPECS['DUQ']
base, cov = run_strategy_comparison(events, prices, spy, spec, open_prices=opens)
saved = pd.read_csv('data/processed/backtest_duq.csv',parse_dates=['date'])
print('REPRODUCTION_MAX_NAV_DIFFERENCE',float((base.disclosed_nav-saved.disclosed_nav).abs().max()))
rows=[]
def record(name, frame):
    m=performance_summary(frame).set_index('portfolio')
    rows.append({'scenario':name,'start':str(frame.date.iloc[0].date()),'end':str(frame.date.iloc[-1].date()),'cagr':m.loc['Disclosed top positions','cagr'],'terminal_nav':frame.disclosed_nav.iloc[-1],'benchmark_cagr':m.loc['Benchmark buy-and-hold','cagr']})
record('Current top 10, SPY',base)
for label,params in [('Full mapped book',dict(top_n=None)),('Top 10, 100 bps',dict(transaction_cost_bps=100)),('Top 10, 5-day delay',dict(execution_delay_sessions=5))]:
    frame,_=run_strategy_comparison(events,prices,spy,replace(spec,**params),open_prices=opens)
    record(label,frame)
frame,_=run_strategy_comparison(events,prices,qqq,spec,open_prices=opens)
record('Current top 10, QQQ',frame)
meta=events[['snapshot_accession','available_at','report_period']].drop_duplicates().sort_values('available_at')
meta['stale']=pd.to_datetime(meta.report_period).lt(pd.to_datetime(meta.report_period).cummax())
stale=meta[meta.stale]
print('STALE_EVENTS',stale.to_json(orient='records'))
frame,_=run_strategy_comparison(events[~events.snapshot_accession.isin(stale.snapshot_accession)],prices,spy,spec,open_prices=opens)
record('Ignore older-report amendments',frame)
common=events[events.put_call.fillna('').eq('')].copy()
coverage_rows=[]
cash_signals=[]
missing_rows=[]
for (accession, available), group in common.groupby(['snapshot_accession','available_at']):
    security=group.groupby('cusip',as_index=False).agg(market_value_usd=('market_value_usd','sum'),ticker_clean=('ticker_clean','first'),issuer=('issuer','first'))
    top=security.nlargest(10,'market_value_usd').copy()
    total=security.market_value_usd.sum()
    top_total=top.market_value_usd.sum()
    when=pd.to_datetime(available,utc=True).tz_convert(None).normalize()
    loc=prices.index.searchsorted(when,side='right')
    execution=prices.index[loc] if loc<len(prices) else None
    mapped=security.ticker_clean.notna()
    priced=top.ticker_clean.map(lambda t: execution is not None and t in prices and pd.notna(prices.at[execution,t]))
    coverage_rows.append(dict(available_at=available,report_period=group.report_period.iloc[0],stock_rows=len(group),mapped_value_coverage=security.loc[mapped,'market_value_usd'].sum()/total,raw_top10_price_coverage=top.loc[priced,'market_value_usd'].sum()/top_total))
    missing_rows.extend(top[~priced].assign(available_at=available,original_top10_weight=lambda x:x.market_value_usd/top_total).to_dict('records'))
    for _,item in top[priced].iterrows():
        cash_signals.append(dict(available_at=available,ticker_clean=item.ticker_clean,target_weight=item.market_value_usd/top_total,max_holding_sessions=63))
    cash_signals.append(dict(available_at=available,ticker_clean='AUDIT_CASH',target_weight=1-top.loc[priced,'market_value_usd'].sum()/top_total,max_holding_sessions=63))
raw=pd.DataFrame(coverage_rows).sort_values('available_at')
raw.to_csv(out/'duquesne_mapping_coverage.csv',index=False)
pd.DataFrame(missing_rows).to_csv(out/'duquesne_unpriced_original_top10.csv',index=False)
print('MAPPING_COVERAGE',raw[['mapped_value_coverage','raw_top10_price_coverage']].describe().to_string())
print('WORST',raw.nsmallest(6,'raw_top10_price_coverage').to_string(index=False))
print('LARGEST_MISSING',pd.DataFrame(missing_rows).nlargest(8,'original_top10_weight')[['available_at','issuer','ticker_clean','original_top10_weight']].to_string(index=False))
# Isolate a diagnostic engine that preserves residual cash instead of normalizing
# the executable holdings to 100%. No production function or data is changed.
source = inspect.getsource(run_event_backtest)
needle = "max(float(weight), 0.0) / total"
assert source.count(needle) == 1
namespace = vars(backtest_module).copy()
exec(source.replace(needle, "max(float(weight), 0.0) / max(total, 1.0)"), namespace)
partial_signals = pd.DataFrame(cash_signals)
partial_signals = partial_signals[partial_signals.ticker_clean.ne('AUDIT_CASH')]
cash = namespace['run_event_backtest'](partial_signals, prices, spy, transaction_cost_bps=10)
cash=cash[cash.date.ge(base.date.iloc[0])].copy()
years=(cash.date.iloc[-1]-cash.date.iloc[0]).days/365.25
rows.append(dict(scenario='Original top 10; unpriced allocations held as zero-return cash (diagnostic)',start=str(cash.date.iloc[0].date()),end=str(cash.date.iloc[-1].date()),cagr=cash.strategy_nav.iloc[-1]**(1/years)-1,terminal_nav=cash.strategy_nav.iloc[-1],benchmark_cagr=rows[0]['benchmark_cagr']))
# Replay the default engine's next-close arithmetic for attribution and missing-price exits.
signals=build_disclosed_book_signals(events,spec)
signals,_=filter_signals_for_price_coverage(signals,prices)
tickers=signals.ticker_clean.unique().tolist(); p=prices[tickers]; ret=p.pct_change(fill_method=None).fillna(0)
schedule={}
for ts,g in signals.groupby('available_at',sort=True):
    loc=p.index.searchsorted(pd.Timestamp(ts).tz_convert(None).normalize(),side='right')
    if loc<len(p): schedule[loc]=g.groupby('ticker_clean').target_weight.sum().reindex(tickers,fill_value=0).to_numpy()
w=np.zeros(len(tickers)); expiry=None; losses=[]; contributions=[]; nav=1
for loc,date in enumerate(p.index):
    daily=w*ret.iloc[loc].to_numpy(); gross=daily.sum()
    for j in np.flatnonzero(np.abs(daily)>0.01): contributions.append(dict(date=date,ticker=tickers[j],weight=w[j],security_return=ret.iloc[loc,j],contribution=daily[j]))
    w=w*(1+ret.iloc[loc].to_numpy())/(1+gross)
    missing=(~p.iloc[loc].notna().to_numpy()) & (w>1e-10)
    for j in np.flatnonzero(missing): losses.append(dict(date=date,ticker=tickers[j],weight=w[j]))
    w=np.where(p.iloc[loc].notna(),w,0)
    cost=0
    if expiry is not None and loc>=expiry and loc not in schedule: cost+=abs(w).sum()*.001;w=np.zeros(len(w));expiry=None
    if loc in schedule: cost+=abs(schedule[loc]-w).sum()*.001;w=schedule[loc].copy();expiry=loc+63
    nav*=1+gross-cost
print('REPLAY_NAV',nav,'MISSING_PRICE_EXITS',losses)
pd.DataFrame(contributions).to_csv(out/'duquesne_large_daily_contributions.csv',index=False)
print('TOP_CONTRIBUTIONS',pd.DataFrame(contributions).nlargest(8,'contribution').to_string(index=False))
result=pd.DataFrame(rows);result.to_csv(out/'duquesne_audit_scenarios.csv',index=False)
print('SCENARIOS',result.to_string(index=False))
