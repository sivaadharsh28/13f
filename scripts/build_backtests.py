"""Build audited historical simulations over complete mapped universes."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil

import pandas as pd

from thirteenf.backtest import (STRATEGY_SPECS, PriceDataError, run_strategy_comparison,
                                run_parameter_sweep, common_backtest_window,
                                full_period_comparison, performance_summary)
from thirteenf.market_data import download_adjusted_ohlc
from thirteenf.security_history import load_resolved_events
from thirteenf.storage import save_snapshot

BENCHMARK_SYMBOLS = ["SPY", "QQQ"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", default="data/processed/sec_holdings_events.csv")
    parser.add_argument("--prices-dir", default="data/prices")
    parser.add_argument("--output-dir", default="data/processed")
    parser.add_argument("--start", default="2014-01-01")
    parser.add_argument("--end", required=True, help="Exclusive reproducible price cutoff")
    parser.add_argument("--reuse-prices-dir", help="Reuse complete histories; fetch missing symbols only")
    parser.add_argument("--sweep", action="store_true")
    args = parser.parse_args()
    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    price_dir = Path(args.prices_dir); price_dir.mkdir(parents=True, exist_ok=True)
    # These are retained strategy assumptions, not selected by realized CAGR.
    policy = {"version": 2, "fixed_strategies": {k: asdict(v) for k,v in STRATEGY_SPECS.items()},
              "evaluation_note": "One continuous historical simulation over the earliest common availability of all strategy funds; no development/test split. Existing positions carry into the common window.",
              "unpriced_policy": "residual cash; below 90% original selected value coverage, whole event targets cash",
              "valuation_policy": "reject missing/nonpositive held prices or ten unchanged closes; no forward fill",
              "corporate_action_policy": "vendor-adjusted dividends/splits; only sourced share-class continuations; unresolved mergers/delistings excluded explicitly"}
    policy_path = out / "simulation_policy.json"
    if policy_path.exists():
        previous_policy = json.loads(policy_path.read_text(encoding="utf-8"))
        # Reporting windows can change without changing the trading assumptions.
        rule_keys = ("version", "fixed_strategies", "unpriced_policy", "valuation_policy", "corporate_action_policy")
        if any(previous_policy.get(key) != policy.get(key) for key in rule_keys):
            raise ValueError("Fixed trading policy changed. Use a separate output directory for a new experiment.")
    policy_path.write_text(json.dumps(policy, indent=2), encoding="utf-8")
    events = load_resolved_events(args.events, "data/security_master.csv", "data/historical_security_overrides.csv")
    save_snapshot(events, out / "sec_holdings_events_resolved.csv")
    universe = events[events.manager_code.isin(STRATEGY_SPECS) & events.put_call.fillna("").eq("")]
    tickers = sorted(set(universe.ticker_clean.dropna()) | set(BENCHMARK_SYMBOLS))
    save_snapshot(universe[universe.ticker_clean.isna()], out / "unresolved_historical_holdings.csv")
    opens = pd.DataFrame(); closes = pd.DataFrame(); errors = {}
    if args.reuse_prices_dir:
        source = Path(args.reuse_prices_dir)
        closes = pd.read_csv(source / "adjusted_close.csv", index_col=0, parse_dates=True)
        opens = pd.read_csv(source / "adjusted_open.csv", index_col=0, parse_dates=True)
        prior_errors = source / "download_errors.json"
        if prior_errors.exists():
            errors = json.loads(prior_errors.read_text(encoding="utf-8"))
        for frame in (closes, opens):
            frame.drop(index=frame.index[(frame.index < pd.Timestamp(args.start)) | (frame.index >= pd.Timestamp(args.end))], inplace=True)
    missing = [t for t in tickers if t not in closes or t not in opens]
    def fetch(ticker):
        return download_adjusted_ohlc([ticker], args.start, args.end, delay=0, metadata_dir=price_dir / "provenance")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch,t):t for t in missing}
        for future in as_completed(futures):
            ticker = futures[future]
            opening, closing, failures = future.result()
            errors.update(failures)
            if not closing.empty:
                closes = pd.concat([closes.drop(columns=[ticker], errors="ignore"), closing], axis=1)
                errors.pop(ticker, None)
            if not opening.empty:
                opens = pd.concat([opens.drop(columns=[ticker], errors="ignore"), opening], axis=1)
    for benchmark in BENCHMARK_SYMBOLS:
        if benchmark not in closes or benchmark not in opens:
            raise RuntimeError(f"Missing benchmark adjusted prices: {benchmark}")
    closes = closes.sort_index(); opens = opens.sort_index()
    archive = price_dir / "pre_repair"
    archive.mkdir(exist_ok=True)
    for filename in ("adjusted_close.csv", "adjusted_open.csv", "spy.csv", "spy_open.csv", "qqq.csv", "qqq_open.csv", "download_errors.json"):
        current = price_dir / filename
        if current.exists() and not (archive / filename).exists():
            shutil.copy2(current, archive / filename)
    closes.to_csv(price_dir / "adjusted_close.csv"); opens.to_csv(price_dir / "adjusted_open.csv")
    for benchmark in BENCHMARK_SYMBOLS:
        closes[[benchmark]].dropna().to_csv(price_dir / f"{benchmark.lower()}.csv")
        opens[[benchmark]].reindex(closes[benchmark].dropna().index).to_csv(price_dir / f"{benchmark.lower()}_open.csv")
    (price_dir / "download_errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
    manifest = {"policy": policy, "price_start": args.start, "price_end_exclusive": args.end,
                "universe_symbols": tickers, "download_errors": errors,
                "price_provenance_paths": [str(price_dir / "provenance")] + ([str(Path(args.reuse_prices_dir) / "provenance")] if args.reuse_prices_dir else []),
                "source_events_sha256": hashlib.sha256(Path(args.events).read_bytes()).hexdigest(),
                "security_master_sha256": hashlib.sha256(Path("data/security_master.csv").read_bytes()).hexdigest(),
                "price_sha256": hashlib.sha256((price_dir / "adjusted_close.csv").read_bytes()).hexdigest(),
                "events_sha256": hashlib.sha256((out / "sec_holdings_events_resolved.csv").read_bytes()).hexdigest(),
                "override_sha256": hashlib.sha256(Path("data/historical_security_overrides.csv").read_bytes()).hexdigest()}
    (out / "simulation_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    comparisons = {}
    for code, spec in STRATEGY_SPECS.items():
        for benchmark in BENCHMARK_SYMBOLS:
            suffix = code.lower() if benchmark == "SPY" else f"{code.lower()}_{benchmark.lower()}"
            result_path = out / f"backtest_{suffix}.csv"
            old = out / "pre_repair"; old.mkdir(exist_ok=True)
            if result_path.exists() and not (old / result_path.name).exists():
                shutil.copy2(result_path, old / result_path.name)
            status_path = out / f"backtest_{suffix}_status.json"
            try:
                comparison, coverage = run_strategy_comparison(
                    events, closes, closes[benchmark].dropna(), spec, open_prices=opens,
                    benchmark_open_prices=opens[benchmark],
                )
            except PriceDataError as exc:
                status_path.write_text(json.dumps({"version":2,"status":"invalid","error":str(exc)}),encoding="utf-8")
                print(code, benchmark, "INVALID", exc, flush=True)
                continue
            save_snapshot(comparison, result_path)
            save_snapshot(coverage, out / f"backtest_{suffix}_coverage.csv")
            comparisons[suffix] = comparison
            status_path.write_text(json.dumps({"version":2,"status":"valid","kind":"historical_simulation"}),encoding="utf-8")
            print(code, benchmark, "saved", len(comparison), "sessions;", coverage.status.value_counts().to_dict(), flush=True)
    if len(comparisons) != len(STRATEGY_SPECS) * len(BENCHMARK_SYMBOLS):
        raise RuntimeError("Every fund and benchmark must have valid history before building common-period results.")
    window = common_backtest_window(comparisons)
    for suffix, comparison in comparisons.items():
        full = full_period_comparison(comparison, *window)
        metrics = performance_summary(full)
        metrics["start_date"], metrics["end_date"] = window
        save_snapshot(metrics, out / f"backtest_{suffix}_evaluation.csv")
    if args.sweep:
        for code, spec in STRATEGY_SPECS.items():
            print(code, "running fixed sensitivity grid", flush=True)
            sweep = run_parameter_sweep(events, closes, closes.SPY.dropna(), spec,
                transaction_cost_bps_values=(10,100), open_prices=opens, benchmark_open_prices=opens.SPY,
                evaluation_window=window)
            save_snapshot(sweep, out / f"backtest_{code.lower()}_sensitivity.csv")
            print(code, "sensitivity grid saved", flush=True)


if __name__ == "__main__":
    main()
