from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import json
import pandas as pd
from thirteenf.security_history import load_resolved_events
from thirteenf.market_data import download_adjusted_ohlc
out=Path('data/prices/repaired');out.mkdir(parents=True,exist_ok=True)
e=load_resolved_events('data/processed/sec_holdings_events.csv','data/security_master.csv','data/historical_security_overrides.csv')
e.to_csv('data/processed/sec_holdings_events_resolved.csv',index=False)
u=e[e.manager_code.isin(['DUQ','AM','THIEL']) & e.put_call.fillna('').eq('')]
tickers=sorted(set(u.ticker_clean.dropna())|{'SPY','QQQ'})
u[u.ticker_clean.isna()].to_csv('reports/unresolved_historical_holdings.csv',index=False)
print('Downloading complete mapped universe:',len(tickers),flush=True)
opens=[];closes=[];errors={}
def fetch(t):
    return download_adjusted_ohlc([t],'2014-01-01','2026-09-12',delay=0,metadata_dir=out/'provenance')
with ThreadPoolExecutor(max_workers=4) as pool:
    futures={pool.submit(fetch,t):t for t in tickers}
    for n,future in enumerate(as_completed(futures),1):
        o,c,err=future.result();errors.update(err)
        if not c.empty:closes.append(c)
        if not o.empty:opens.append(o)
        if n%25==0:print(n,'/',len(tickers),'errors',len(errors),flush=True)
if closes:pd.concat(closes,axis=1).sort_index().to_csv(out/'adjusted_close.csv')
if opens:pd.concat(opens,axis=1).sort_index().to_csv(out/'adjusted_open.csv')
(out/'download_errors.json').write_text(json.dumps(errors,indent=2),encoding='utf-8')
(out/'universe.json').write_text(json.dumps(tickers,indent=2),encoding='utf-8')
print('Complete:',len(closes),'symbols;',len(errors),'errors',flush=True)
