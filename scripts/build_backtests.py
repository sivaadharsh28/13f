"""Build persisted manager backtest comparisons for the Streamlit app."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from thirteenf.backtest import STRATEGY_SPECS, build_disclosed_book_signals, run_strategy_comparison
from thirteenf.market_data import download_adjusted_close
from thirteenf.storage import save_snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", default="data/processed/sec_holdings_events.csv")
    parser.add_argument("--prices-dir", default="data/prices")
    parser.add_argument("--output-dir", default="data/processed")
    parser.add_argument("--start", default="2014-01-01")
    parser.add_argument("--end")
    args = parser.parse_args()

    events = pd.read_csv(args.events, dtype={"cusip": str})
    signal_sets = [build_disclosed_book_signals(events, spec) for spec in STRATEGY_SPECS.values()]
    tickers = sorted({
        ticker for signals in signal_sets for ticker in signals.get("ticker_clean", pd.Series(dtype=str)).dropna()
    })
    prices, errors = download_adjusted_close(tickers + ["SPY"], args.start, args.end)
    if "SPY" not in prices:
        raise RuntimeError(f"SPY benchmark download failed: {errors.get('SPY', 'missing result')}")

    prices_dir = Path(args.prices_dir)
    prices_dir.mkdir(parents=True, exist_ok=True)
    prices.drop(columns="SPY", errors="ignore").to_csv(prices_dir / "adjusted_close.csv")
    prices[["SPY"]].to_csv(prices_dir / "spy.csv")
    (prices_dir / "download_errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")

    output_dir = Path(args.output_dir)
    for code, spec in STRATEGY_SPECS.items():
        comparison, coverage = run_strategy_comparison(
            events, prices.drop(columns="SPY", errors="ignore"), prices["SPY"], spec,
        )
        save_snapshot(comparison, output_dir / f"backtest_{code.lower()}.csv")
        save_snapshot(coverage, output_dir / f"backtest_{code.lower()}_coverage.csv")
        mean_coverage = coverage["weight_coverage"].mean() if not coverage.empty else 0.0
        print(f"{code}: {len(comparison)} sessions; mean signal coverage {mean_coverage:.1%}")
    print(f"Price symbols: {len(prices.columns) - 1}; failures: {len(errors)}")


if __name__ == "__main__":
    main()
