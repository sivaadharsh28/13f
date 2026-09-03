"""Point-in-time strategy construction and event-driven portfolio testing."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class StrategySpec:
    manager_code: str
    top_n: int = 10
    max_holding_sessions: int = 63
    transaction_cost_bps: float = 10.0
    benchmark: str = "SPY"


STRATEGY_SPECS = {
    "DUQ": StrategySpec("DUQ", top_n=10, max_holding_sessions=63),
    "AM": StrategySpec("AM", top_n=10, max_holding_sessions=63),
    "THIEL": StrategySpec("THIEL", top_n=10, max_holding_sessions=63),
}


def build_disclosed_book_signals(
    event_holdings: pd.DataFrame,
    spec: StrategySpec,
) -> pd.DataFrame:
    """Create long-only targets from information known at each filing event.

    Options are excluded because 13F option rows report underlying share
    equivalents, not directly investable option market values.
    """
    required = {
        "manager_code", "snapshot_accession", "available_at", "ticker_clean",
        "market_value_usd", "put_call", "report_period",
    }
    missing = required - set(event_holdings.columns)
    if missing:
        raise KeyError(f"Event holdings missing columns: {sorted(missing)}")
    rows = event_holdings[event_holdings["manager_code"] == spec.manager_code].copy()
    rows = rows[rows["ticker_clean"].notna() & rows["put_call"].fillna("").eq("")]
    signals: list[pd.DataFrame] = []
    for (_, available_at), snapshot in rows.groupby(["snapshot_accession", "available_at"], sort=True):
        group_columns = ["ticker_clean", "report_period"]
        if "sector" in snapshot.columns:
            group_columns.append("sector")
        per_security = (
            snapshot.groupby(group_columns, as_index=False, dropna=False)["market_value_usd"]
            .sum().nlargest(spec.top_n, "market_value_usd")
        )
        total = per_security["market_value_usd"].sum()
        if total <= 0:
            continue
        per_security["target_weight"] = per_security["market_value_usd"] / total
        per_security["available_at"] = pd.to_datetime(available_at, utc=True)
        per_security["manager_code"] = spec.manager_code
        per_security["max_holding_sessions"] = spec.max_holding_sessions
        signals.append(per_security)
    columns = [
        "available_at", "manager_code", "report_period", "ticker_clean",
        "target_weight", "max_holding_sessions",
    ]
    if "sector" in event_holdings.columns:
        columns.insert(4, "sector")
    return pd.concat(signals, ignore_index=True)[columns] if signals else pd.DataFrame(columns=columns)


def build_sector_balanced_baseline(
    signals: pd.DataFrame,
    sector_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Give each represented sector equal capital and each member equal weight."""
    result = signals.copy()
    if "sector" not in result.columns:
        result["sector"] = result["ticker_clean"].map(sector_map or {}).fillna("Unknown")
    else:
        result["sector"] = result["sector"].fillna("Unknown")
    group_columns = ["available_at", "manager_code", "report_period"]
    counts = result.groupby(group_columns + ["sector"])["ticker_clean"].transform("count")
    sector_counts = result.groupby(group_columns)["sector"].transform("nunique")
    result["target_weight"] = 1.0 / sector_counts / counts
    return result


def _execution_session(index: pd.DatetimeIndex, available_at: pd.Timestamp) -> pd.Timestamp | None:
    if index.tz is not None:
        available_date = available_at.tz_convert(index.tz).normalize()
    else:
        available_date = available_at.tz_convert(None).normalize() if available_at.tzinfo else available_at.normalize()
    location = index.searchsorted(available_date, side="right")
    return index[location] if location < len(index) else None


def run_event_backtest(
    signals: pd.DataFrame,
    prices: pd.DataFrame,
    benchmark_prices: pd.Series,
    transaction_cost_bps: float = 10.0,
) -> pd.DataFrame:
    """Backtest targets at the close after the first post-disclosure session."""
    if signals.empty:
        return pd.DataFrame(columns=[
            "date", "strategy_return", "strategy_nav", "benchmark_return",
            "benchmark_nav", "excess_nav", "turnover", "cost", "gross_exposure",
        ])
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError("prices must use a DatetimeIndex")
    prices = prices.sort_index().copy().apply(pd.to_numeric, errors="coerce")
    benchmark_prices = benchmark_prices.reindex(prices.index).ffill()
    returns = prices.pct_change(fill_method=None).fillna(0.0)
    benchmark_returns = benchmark_prices.pct_change(fill_method=None).fillna(0.0)
    events: dict[pd.Timestamp, tuple[dict[str, float], int]] = {}
    for available_at, frame in signals.groupby("available_at", sort=True):
        timestamp = pd.to_datetime(available_at, utc=True)
        execution = _execution_session(prices.index, timestamp)
        if execution is None:
            continue
        targets = frame.groupby("ticker_clean")["target_weight"].sum().to_dict()
        missing = set(targets) - set(prices.columns)
        if missing:
            raise KeyError(f"Missing prices for: {sorted(missing)}")
        total = sum(max(float(weight), 0.0) for weight in targets.values())
        normalized = {ticker: max(float(weight), 0.0) / total for ticker, weight in targets.items()} if total else {}
        horizon = int(frame["max_holding_sessions"].iloc[0]) if "max_holding_sessions" in frame else len(prices)
        events[execution] = (normalized, horizon)

    weights: dict[str, float] = {}
    expiry_location: int | None = None
    nav = 1.0
    benchmark_nav = 1.0
    output: list[dict[str, float | pd.Timestamp]] = []
    cost_rate = transaction_cost_bps / 10_000
    for location, date in enumerate(prices.index):
        asset_returns = {
            ticker: float(returns.at[date, ticker]) if pd.notna(returns.at[date, ticker]) else 0.0
            for ticker in prices.columns
        }
        strategy_return = sum(weights.get(ticker, 0.0) * asset_returns[ticker] for ticker in prices.columns)
        benchmark_return = float(benchmark_returns.at[date])
        gross_return = strategy_return
        if 1 + gross_return != 0:
            weights = {
                ticker: weight * (1 + asset_returns[ticker]) / (1 + gross_return)
                for ticker, weight in weights.items()
            }
        # Treat the first missing quote after a security's history as a cash
        # realization at its last observed adjusted close. Corporate-action
        # cash terms still require a better institutional price source.
        weights = {
            ticker: weight for ticker, weight in weights.items()
            if ticker in prices.columns and pd.notna(prices.at[date, ticker])
        }
        turnover = 0.0
        cost = 0.0
        if expiry_location is not None and location >= expiry_location and date not in events:
            turnover = sum(abs(weight) for weight in weights.values())
            weights = {}
            expiry_location = None
        if date in events:
            targets, horizon = events[date]
            turnover += sum(abs(targets.get(ticker, 0.0) - weights.get(ticker, 0.0)) for ticker in set(targets) | set(weights))
            weights = targets
            expiry_location = location + horizon
        cost = turnover * cost_rate
        strategy_return -= cost
        nav *= 1 + strategy_return
        benchmark_nav *= 1 + benchmark_return
        output.append({
            "date": date, "strategy_return": strategy_return, "strategy_nav": nav,
            "benchmark_return": benchmark_return, "benchmark_nav": benchmark_nav,
            "excess_nav": nav / benchmark_nav if benchmark_nav else np.nan,
            "turnover": turnover, "cost": cost,
            "gross_exposure": sum(weights.values()),
        })
    return pd.DataFrame(output)


def filter_signals_for_price_coverage(
    signals: pd.DataFrame,
    prices: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Drop unavailable securities per event and report disclosed-weight coverage."""
    if signals.empty:
        return signals.copy(), pd.DataFrame(columns=[
            "available_at", "original_positions", "priced_positions", "weight_coverage",
        ])
    normalized_prices = prices.apply(pd.to_numeric, errors="coerce").sort_index()
    kept: list[pd.DataFrame] = []
    diagnostics: list[dict[str, object]] = []
    for available_at, event in signals.groupby("available_at", sort=True):
        execution = _execution_session(
            normalized_prices.index, pd.to_datetime(available_at, utc=True),
        )
        available = set()
        if execution is not None:
            available = {
                ticker for ticker in event["ticker_clean"].unique()
                if ticker in normalized_prices.columns and pd.notna(normalized_prices.at[execution, ticker])
            }
        selected = event[event["ticker_clean"].isin(available)].copy()
        coverage = float(selected["target_weight"].sum())
        diagnostics.append({
            "available_at": available_at,
            "original_positions": int(event["ticker_clean"].nunique()),
            "priced_positions": int(selected["ticker_clean"].nunique()),
            "weight_coverage": coverage,
        })
        if coverage > 0:
            selected["target_weight"] = selected["target_weight"] / coverage
            kept.append(selected)
    filtered = pd.concat(kept, ignore_index=True) if kept else signals.iloc[0:0].copy()
    return filtered, pd.DataFrame(diagnostics)


def run_strategy_comparison(
    event_holdings: pd.DataFrame,
    prices: pd.DataFrame,
    benchmark_prices: pd.Series,
    spec: StrategySpec,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run disclosed-weight and sector-balanced variants against buy-and-hold."""
    signals = build_disclosed_book_signals(event_holdings, spec)
    signals, coverage = filter_signals_for_price_coverage(signals, prices)
    if signals.empty:
        return pd.DataFrame(), coverage
    disclosed = run_event_backtest(
        signals, prices, benchmark_prices, transaction_cost_bps=spec.transaction_cost_bps,
    )
    balanced_signals = build_sector_balanced_baseline(signals)
    balanced = run_event_backtest(
        balanced_signals, prices, benchmark_prices,
        transaction_cost_bps=spec.transaction_cost_bps,
    )
    comparison = disclosed[[
        "date", "strategy_return", "strategy_nav", "benchmark_return",
        "benchmark_nav", "turnover", "cost", "gross_exposure",
    ]].rename(columns={
        "strategy_return": "disclosed_return",
        "strategy_nav": "disclosed_nav",
        "turnover": "disclosed_turnover",
        "cost": "disclosed_cost",
        "gross_exposure": "disclosed_exposure",
    })
    comparison = comparison.merge(
        balanced[["date", "strategy_return", "strategy_nav", "turnover", "cost", "gross_exposure"]]
        .rename(columns={
            "strategy_return": "sector_balanced_return",
            "strategy_nav": "sector_balanced_nav",
            "turnover": "sector_balanced_turnover",
            "cost": "sector_balanced_cost",
            "gross_exposure": "sector_balanced_exposure",
        }),
        on="date", how="inner",
    )
    invested = comparison["disclosed_turnover"].gt(0)
    if invested.any():
        comparison = comparison.loc[invested.idxmax():].reset_index(drop=True)
        benchmark_start = float(comparison.loc[0, "benchmark_nav"])
        if benchmark_start:
            comparison["benchmark_nav"] = comparison["benchmark_nav"] / benchmark_start
    return comparison, coverage


def performance_summary(comparison: pd.DataFrame) -> pd.DataFrame:
    """Return comparable annualized metrics for the three NAV series."""
    if comparison.empty:
        return pd.DataFrame(columns=[
            "portfolio", "total_return", "cagr", "annualized_volatility", "max_drawdown",
        ])
    configurations = {
        "Disclosed top positions": ("disclosed_nav", "disclosed_return"),
        "Sector-balanced baseline": ("sector_balanced_nav", "sector_balanced_return"),
        "SPY buy-and-hold": ("benchmark_nav", "benchmark_return"),
    }
    elapsed_days = max((pd.to_datetime(comparison["date"]).iloc[-1] - pd.to_datetime(comparison["date"]).iloc[0]).days, 1)
    rows: list[dict[str, float | str]] = []
    for label, (nav_column, return_column) in configurations.items():
        nav = pd.to_numeric(comparison[nav_column], errors="coerce").dropna()
        returns = pd.to_numeric(comparison[return_column], errors="coerce").dropna()
        if nav.empty:
            continue
        total_return = float(nav.iloc[-1] / nav.iloc[0] - 1)
        cagr = float((nav.iloc[-1] / nav.iloc[0]) ** (365.25 / elapsed_days) - 1) if nav.iloc[0] > 0 else np.nan
        drawdown = nav / nav.cummax() - 1
        rows.append({
            "portfolio": label,
            "total_return": total_return,
            "cagr": cagr,
            "annualized_volatility": float(returns.std(ddof=0) * np.sqrt(252)),
            "max_drawdown": float(drawdown.min()),
        })
    return pd.DataFrame(rows)
