"""Point-in-time strategy construction and event-driven portfolio testing."""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import product

import numpy as np
import pandas as pd


AVAILABILITY_MODELS = {
    "Actual SEC filing": "filing_date",
}

EXECUTION_PROFILES = {
    "Next close": {"execution_timing": "next_close", "execution_delay_sessions": 0},
    "Next open": {"execution_timing": "next_open", "execution_delay_sessions": 0},
    "1-day delay": {"execution_timing": "next_close", "execution_delay_sessions": 1},
    "5-day delay": {"execution_timing": "next_close", "execution_delay_sessions": 5},
}

PORTFOLIO_SIZE_OPTIONS = {
    "Top 5": 5,
    "Top 10": 10,
    "Top 20": 20,
    "Full disclosed book": None,
}

TRANSACTION_COST_BPS_OPTIONS = (10, 25, 50, 100)


@dataclass(frozen=True)
class StrategySpec:
    manager_code: str
    top_n: int | None = 10
    max_holding_sessions: int = 63
    transaction_cost_bps: float = 10.0
    benchmark: str = "SPY"
    availability_model: str = "filing_date"
    execution_timing: str = "next_close"
    execution_delay_sessions: int = 0
    minimum_coverage: float = 0.90


STRATEGY_SPECS = {
    "DUQ": StrategySpec("DUQ", top_n=10, max_holding_sessions=63),
    "AM": StrategySpec("AM", top_n=10, max_holding_sessions=63),
    "THIEL": StrategySpec("THIEL", top_n=10, max_holding_sessions=63),
}


def _top_n_label(top_n: int | None) -> str:
    return "Full disclosed book" if top_n is None else f"Top {top_n}"


def _signal_available_at(snapshot: pd.DataFrame, raw_available_at: object, spec: StrategySpec) -> pd.Timestamp:
    if spec.availability_model != "filing_date":
        raise ValueError(f"Unknown availability model: {spec.availability_model}")
    return pd.to_datetime(raw_available_at, utc=True)


def build_disclosed_book_signals(event_holdings: pd.DataFrame, spec: StrategySpec) -> pd.DataFrame:
    """Rank original non-option securities, preserving unmapped allocations."""
    required = {"manager_code", "snapshot_accession", "available_at", "ticker_clean",
                "market_value_usd", "put_call", "report_period"}
    if required - set(event_holdings):
        raise KeyError(f"Event holdings missing columns: {sorted(required - set(event_holdings))}")
    columns = ["available_at", "manager_code", "report_period", "ticker_clean", "sector",
               "security_id", "target_weight", "max_holding_sessions", "event_status",
               "universe_mapping_coverage", "selected_universe_weight"]
    if spec.top_n is not None and spec.top_n <= 0:
        return pd.DataFrame(columns=columns)
    rows = event_holdings[event_holdings.manager_code.eq(spec.manager_code)].copy()
    rows["available_at"] = pd.to_datetime(rows["available_at"], utc=True, errors="raise")
    rows["report_period"] = pd.to_datetime(rows["report_period"], errors="raise")
    latest_period = pd.Timestamp.min
    output = []
    for (_, accession), snapshot in rows.sort_values(["available_at", "report_period"]).groupby(
        ["available_at", "snapshot_accession"], sort=True
    ):
        period = snapshot.report_period.max()
        available = _signal_available_at(snapshot, snapshot.available_at.iloc[0], spec)
        stale = period < latest_period
        latest_period = max(period, latest_period)
        stock = snapshot[snapshot.put_call.fillna("").eq("")].copy()
        stock["market_value_usd"] = pd.to_numeric(stock.market_value_usd, errors="raise")
        stock = stock[stock.market_value_usd.gt(0)]
        stock["ticker_clean"] = stock.ticker_clean.replace(r"^\s*$", pd.NA, regex=True)
        if "cusip" in stock:
            stock["security_id"] = stock.cusip.fillna("").astype(str)
        else:
            stock["security_id"] = stock.ticker_clean.fillna(pd.Series(stock.index.astype(str), index=stock.index))
        stock["sector"] = stock.get("sector", pd.Series("Unknown", index=stock.index)).fillna("Unknown")
        grouped = stock.groupby("security_id", as_index=False).agg(
            market_value_usd=("market_value_usd", "sum"), ticker_clean=("ticker_clean", "first"),
            sector=("sector", "first"),
        )
        total = grouped.market_value_usd.sum()
        mapping = grouped.loc[grouped.ticker_clean.notna(), "market_value_usd"].sum() / total if total else 1.0
        selected = grouped.sort_values(["market_value_usd", "security_id"], ascending=[False, True])
        if spec.top_n is not None:
            selected = selected.head(spec.top_n).copy()
        selected_total = selected.market_value_usd.sum()
        if selected.empty or stale:
            selected = pd.DataFrame([dict(ticker_clean=pd.NA, sector="Unknown", security_id="CASH", target_weight=0.0)])
        else:
            selected["target_weight"] = selected.market_value_usd / selected_total
        selected["available_at"] = available
        selected["manager_code"] = spec.manager_code
        selected["report_period"] = period
        selected["max_holding_sessions"] = spec.max_holding_sessions
        selected["event_status"] = "stale_report_ignored" if stale else ("empty_book" if not total else "candidate")
        selected["universe_mapping_coverage"] = mapping
        selected["selected_universe_weight"] = selected_total / total if total else 0.0
        output.append(selected[columns])
    return pd.concat(output, ignore_index=True) if output else pd.DataFrame(columns=columns)


def build_sector_balanced_baseline(signals: pd.DataFrame, sector_map: dict[str, str] | None = None) -> pd.DataFrame:
    """Allocate sectors before price filtering so missing constituents keep cash."""
    result = signals.copy()
    result["sector"] = result.get("sector", result.ticker_clean.map(sector_map or {})).fillna("Unknown")
    keys = ["available_at", "manager_code", "report_period"]
    counts = result.groupby(keys + ["sector"])["target_weight"].transform("size")
    sector_counts = result.groupby(keys)["sector"].transform("nunique")
    result["target_weight"] = (1.0 / sector_counts / counts).where(result.target_weight.gt(0), 0.0)
    return result


def _execution_session(
    index: pd.DatetimeIndex,
    available_at: pd.Timestamp,
    execution_delay_sessions: int = 0,
) -> pd.Timestamp | None:
    if execution_delay_sessions < 0:
        raise ValueError("execution_delay_sessions must be non-negative")
    if index.tz is not None:
        available_date = available_at.tz_convert(index.tz).normalize()
    else:
        available_date = available_at.tz_convert(None).normalize() if available_at.tzinfo else available_at.normalize()
    location = index.searchsorted(available_date, side="right") + execution_delay_sessions
    return index[location] if location < len(index) else None


def _align_open_prices(close_prices: pd.DataFrame, open_prices: pd.DataFrame | None) -> pd.DataFrame | None:
    if open_prices is None:
        return None
    return open_prices.reindex(index=close_prices.index, columns=close_prices.columns).apply(pd.to_numeric, errors="coerce")


class PriceDataError(ValueError):
    """A required held-security or benchmark valuation cannot be established."""


def run_event_backtest(
    signals: pd.DataFrame, prices: pd.DataFrame, benchmark_prices: pd.Series,
    transaction_cost_bps: float = 10.0, execution_timing: str = "next_close",
    execution_delay_sessions: int = 0, open_prices: pd.DataFrame | None = None,
    benchmark_open_prices: pd.Series | None = None,
) -> pd.DataFrame:
    """Simulate residual cash explicitly; fail on missing held-security prices."""
    columns = ["date", "strategy_return", "strategy_nav", "benchmark_return", "benchmark_nav",
               "excess_nav", "turnover", "cost", "gross_exposure"]
    if signals.empty:
        return pd.DataFrame(columns=columns)
    if execution_timing not in {"next_close", "next_open"}:
        raise ValueError(f"Unknown execution timing: {execution_timing}")
    if not 0 <= transaction_cost_bps < 5000:
        raise ValueError("Transaction cost must be nonnegative and below 5000 bps")
    if not isinstance(prices.index, pd.DatetimeIndex) or prices.index.has_duplicates:
        raise ValueError("prices require a unique DatetimeIndex")
    prices = prices.sort_index().apply(pd.to_numeric, errors="coerce")
    opening = _align_open_prices(prices, open_prices)
    if execution_timing == "next_open" and opening is None:
        raise ValueError("next_open execution requires adjusted open prices")
    if execution_timing == "next_open" and benchmark_open_prices is None:
        raise ValueError("next_open execution requires adjusted benchmark open prices")
    bench = benchmark_prices.reindex(prices.index)
    bench_open = benchmark_open_prices.reindex(prices.index) if benchmark_open_prices is not None else None
    tickers = list(prices.columns)
    schedule = {}
    for ts, frame in signals.groupby("available_at", sort=True):
        execution = _execution_session(prices.index, pd.to_datetime(ts, utc=True), execution_delay_sessions)
        if execution is None:
            continue
        targets = frame.groupby("ticker_clean").target_weight.sum()
        if set(targets.index) - set(tickers):
            raise PriceDataError(f"Unpriced target: {sorted(set(targets.index) - set(tickers))}")
        weights = targets.reindex(tickers, fill_value=0).to_numpy(dtype=float)
        if not np.isfinite(weights).all() or (weights < 0).any() or weights.sum() > 1.00000001:
            raise ValueError("Target weights must be finite, nonnegative and sum to at most one")
        # The last accepted filing on the same execution session takes precedence.
        schedule[prices.index.get_loc(execution)] = (weights, int(frame.max_holding_sessions.iloc[0]) if "max_holding_sessions" in frame else len(prices))
    if not schedule:
        return pd.DataFrame(columns=columns)
    first = min(schedule)
    values = prices.to_numpy(dtype=float)
    repeated = prices.eq(prices.shift())
    counts = repeated.cumsum()
    stale_closes = (counts - counts.where(~repeated).ffill().fillna(0)).ge(10).to_numpy()
    open_values = opening.to_numpy(dtype=float) if opening is not None else None
    w = np.zeros(len(tickers)); nav = 1.0; benchmark_nav = 1.0; expiry = None
    output = []; cost_rate = transaction_cost_bps / 10000

    def require(values_at_time, held, date, kind):
        bad = (held > 1e-12) & (~np.isfinite(values_at_time) | (values_at_time <= 0))
        if bad.any():
            raise PriceDataError(f"Missing or invalid {kind} on {date.date()}: {[tickers[j] for j in np.flatnonzero(bad)]}; simulation rejected")

    def mark(start, finish, held, date):
        require(start, held, date, "starting valuation")
        require(finish, held, date, "held-security price")
        stale = stale_closes[prices.index.get_loc(date)] & (held > 1e-12)
        if stale.any():
            raise PriceDataError(f"Ten unchanged closes require stale-price review on {date.date()}: {[tickers[j] for j in np.flatnonzero(stale)]}")
        changes = np.divide(finish, start, out=np.ones_like(finish), where=(held > 1e-12)) - 1
        gain = float(held @ changes)
        if 1 + gain <= 0:
            raise PriceDataError("Portfolio value exhausted")
        return gain, held * (1 + changes) / (1 + gain)

    for loc, date in enumerate(prices.index):
        if loc < first:
            output.append(dict(date=date, strategy_return=0., strategy_nav=1., benchmark_return=0., benchmark_nav=1., excess_nav=1., turnover=0., cost=0., gross_exposure=0.))
            continue
        turnover = cost = 0.0
        if not np.isfinite(bench.iloc[loc]) or bench.iloc[loc] <= 0:
            raise PriceDataError(f"Missing benchmark close on {date.date()}")
        if loc == first:
            entry = bench_open.iloc[loc] if execution_timing == "next_open" else bench.iloc[loc]
            if not np.isfinite(entry) or entry <= 0:
                raise PriceDataError(f"Missing benchmark entry price on {date.date()}")
            benchmark_return = float(bench.iloc[loc] / entry - 1)
        else:
            benchmark_return = float(bench.iloc[loc] / bench.iloc[loc - 1] - 1)
        previous = values[loc - 1] if loc else values[loc]
        if loc in schedule and execution_timing == "next_open":
            overnight, w = mark(previous, open_values[loc], w, date)
            targets, horizon = schedule[loc]
            require(open_values[loc], targets, date, "execution open")
            turnover = float(abs(targets - w).sum()); cost = turnover * cost_rate
            w = targets.copy(); expiry = loc + horizon - 1
            intraday, w = mark(open_values[loc], values[loc], w, date)
            factor = (1 + overnight) * (1 - cost) * (1 + intraday)
        else:
            gain, w = mark(previous, values[loc], w, date)
            factor = 1 + gain
        if loc in schedule and execution_timing == "next_close":
            targets, horizon = schedule[loc]
            require(values[loc], targets, date, "execution close")
            turnover = float(abs(targets - w).sum()); cost = turnover * cost_rate
            factor *= 1 - cost
            w = targets.copy(); expiry = loc + horizon
        if expiry is not None and loc >= expiry and (loc not in schedule or execution_timing == "next_open"):
            exit_turnover = float(w.sum()); exit_cost = exit_turnover * cost_rate
            turnover += exit_turnover; cost += exit_cost; factor *= 1 - exit_cost
            w = np.zeros(len(tickers)); expiry = None
        strategy_return = factor - 1
        nav *= factor; benchmark_nav *= 1 + benchmark_return
        output.append(dict(date=date, strategy_return=strategy_return, strategy_nav=nav,
                           benchmark_return=benchmark_return, benchmark_nav=benchmark_nav,
                           excess_nav=nav / benchmark_nav, turnover=turnover, cost=cost, gross_exposure=float(w.sum())))
    return pd.DataFrame(output, columns=columns)


def filter_signals_for_price_coverage(
    signals: pd.DataFrame, prices: pd.DataFrame, execution_delay_sessions: int = 0,
    execution_timing: str = "next_close", open_prices: pd.DataFrame | None = None,
    minimum_coverage: float = 0.90,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Measure original-universe coverage; rejected events explicitly target cash."""
    if not 0 <= minimum_coverage <= 1:
        raise ValueError("minimum_coverage must be between zero and one")
    kept = []; diagnostics = []
    p = prices.sort_index().apply(pd.to_numeric, errors="coerce")
    trade_prices = _align_open_prices(p, open_prices) if execution_timing == "next_open" else p
    for ts, event in signals.groupby("available_at", sort=True):
        status = event.event_status.iloc[0] if "event_status" in event else "candidate"
        original = event.target_weight.sum()
        mapping = float(event.loc[event.ticker_clean.notna(), "target_weight"].sum())
        execution = _execution_session(p.index, pd.to_datetime(ts, utc=True), execution_delay_sessions)
        available = set()
        if execution is not None and trade_prices is not None:
            available = {t for t in event.ticker_clean.dropna().unique() if t in trade_prices
                         and pd.notna(trade_prices.at[execution, t]) and np.isfinite(trade_prices.at[execution, t])
                         and trade_prices.at[execution, t] > 0}
        selected = event[event.ticker_clean.isin(available)].copy()
        coverage = float(selected.target_weight.sum())
        if status == "stale_report_ignored":
            pass
        elif execution is None:
            status = "outside_price_window"
        elif original <= 0:
            status = "empty_book"
        elif coverage + 1e-10 < minimum_coverage:
            status = "rejected_low_coverage"
        else:
            status = "accepted"
        diagnostics.append(dict(
            available_at=ts, execution_date=execution, original_positions=int(event.target_weight.gt(0).sum()),
            priced_positions=int(selected.target_weight.gt(0).sum()), mapping_coverage=mapping,
            universe_mapping_coverage=float(event.universe_mapping_coverage.iloc[0]) if "universe_mapping_coverage" in event else mapping,
            weight_coverage=coverage, executable_value_coverage=coverage, status=status,
            cash_weight=1-coverage if status == "accepted" else 1.0,
            unresolved_securities=";".join(event.loc[event.ticker_clean.isna(), "security_id"].astype(str)) if "security_id" in event else "",
            unpriced_tickers=";".join(sorted(set(event.ticker_clean.dropna()) - available)),
        ))
        if status in {"stale_report_ignored", "outside_price_window"}:
            continue
        if status != "accepted" or selected.empty:
            selected = event.iloc[:1].copy()
            selected["ticker_clean"] = pd.NA
            selected["target_weight"] = 0.0
        kept.append(selected)
    return (pd.concat(kept, ignore_index=True) if kept else signals.iloc[:0].copy(), pd.DataFrame(diagnostics))


def run_strategy_comparison(
    event_holdings: pd.DataFrame, prices: pd.DataFrame, benchmark_prices: pd.Series,
    spec: StrategySpec, open_prices: pd.DataFrame | None = None,
    benchmark_open_prices: pd.Series | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compare strategies and benchmark using one calendar and entry timestamp."""
    original = build_disclosed_book_signals(event_holdings, spec)
    calendar = benchmark_prices.sort_index().index
    tickers = [t for t in original.ticker_clean.dropna().unique() if t in prices]
    prices = prices.reindex(index=calendar, columns=tickers)
    opens = open_prices.reindex(index=calendar, columns=tickers) if open_prices is not None else None
    kwargs = dict(execution_delay_sessions=spec.execution_delay_sessions, execution_timing=spec.execution_timing,
                  open_prices=opens, minimum_coverage=spec.minimum_coverage)
    signals, coverage = filter_signals_for_price_coverage(original, prices, **kwargs)
    if signals.empty:
        return pd.DataFrame(), coverage
    balanced, _ = filter_signals_for_price_coverage(build_sector_balanced_baseline(original), prices, **kwargs)
    # A baseline cannot trade an event rejected by the strategy's original-value gate.
    rejected = set(coverage.loc[coverage.status.ne("accepted"), "available_at"])
    balanced.loc[balanced.available_at.isin(rejected), "target_weight"] = 0.0
    execution = dict(transaction_cost_bps=spec.transaction_cost_bps, execution_timing=spec.execution_timing,
                     execution_delay_sessions=spec.execution_delay_sessions, open_prices=opens,
                     benchmark_open_prices=benchmark_open_prices)
    disclosed = run_event_backtest(signals, prices, benchmark_prices, **execution)
    baseline = run_event_backtest(balanced, prices, benchmark_prices, **execution)
    def rename_result(frame, label):
        return frame.rename(columns={"strategy_return": f"{label}_return", "strategy_nav": f"{label}_nav",
                                     "turnover": f"{label}_turnover", "cost": f"{label}_cost", "gross_exposure": f"{label}_exposure"})
    comparison = rename_result(disclosed.drop(columns="excess_nav"), "disclosed")
    baseline = rename_result(baseline, "sector_balanced")
    comparison = comparison.merge(baseline[["date", "sector_balanced_return", "sector_balanced_nav",
                                          "sector_balanced_turnover", "sector_balanced_cost", "sector_balanced_exposure"]], on="date")
    first = coverage.loc[coverage.status.isin(["accepted", "rejected_low_coverage", "empty_book"]), "execution_date"].min()
    return comparison[comparison.date.ge(first)].reset_index(drop=True), coverage


def common_backtest_window(comparisons: dict[str, pd.DataFrame]) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Earliest shared availability through the latest shared observation."""
    if not comparisons or any(frame.empty for frame in comparisons.values()):
        raise ValueError("Every fund needs backtest data to determine a common period.")
    dates = [pd.to_datetime(frame["date"]) for frame in comparisons.values()]
    start, end = max(d.min() for d in dates), min(d.max() for d in dates)
    if start >= end:
        raise ValueError("Fund histories have no common backtest period.")
    return start, end


def full_period_comparison(comparison: pd.DataFrame, start, end, calendar=None) -> pd.DataFrame:
    """Rebase one continuous history, preserving existing positions and returns."""
    dates = pd.to_datetime(comparison["date"])
    selected = comparison.loc[dates.between(pd.Timestamp(start), pd.Timestamp(end))].copy()
    selected["date"] = pd.to_datetime(selected["date"])
    if calendar is not None and not comparison.empty:
        calendar = pd.DatetimeIndex(calendar)
        # A delayed first trade leaves both strategy and benchmark in cash.
        # Only pad before the first execution; never fill missing held prices.
        initial_dates = calendar[(calendar >= pd.Timestamp(start)) &
                                 (calendar <= pd.Timestamp(end)) & (calendar < dates.min())]
        if len(initial_dates):
            initial = pd.DataFrame(0.0, index=initial_dates, columns=selected.columns.drop("date"))
            initial.index.name = "date"
            selected = pd.concat([initial.reset_index(), selected], ignore_index=True)
    for name in ("disclosed", "sector_balanced", "benchmark"):
        selected[f"{name}_nav"] = (1 + selected[f"{name}_return"]).cumprod()
    return selected.reset_index(drop=True)


def performance_summary(comparison: pd.DataFrame) -> pd.DataFrame:
    """Return comparable annualized metrics for the three NAV series."""
    if comparison.empty:
        return pd.DataFrame(columns=[
            "portfolio", "total_return", "cagr", "annualized_volatility", "max_drawdown",
        ])
    configurations = {
        "Disclosed top positions": ("disclosed_nav", "disclosed_return"),
        "Sector-balanced baseline": ("sector_balanced_nav", "sector_balanced_return"),
        "Benchmark buy-and-hold": ("benchmark_nav", "benchmark_return"),
    }
    elapsed_days = max((pd.to_datetime(comparison["date"]).iloc[-1] - pd.to_datetime(comparison["date"]).iloc[0]).days, 1)
    rows: list[dict[str, float | str]] = []
    for label, (nav_column, return_column) in configurations.items():
        nav = pd.to_numeric(comparison[nav_column], errors="coerce").dropna()
        returns = pd.to_numeric(comparison[return_column], errors="coerce").dropna()
        if nav.empty:
            continue
        terminal_nav = float(nav.iloc[-1])
        drawdown = nav / nav.cummax().clip(lower=1.0) - 1
        volatility = float(returns.std(ddof=0) * np.sqrt(252))
        downside = float(np.sqrt(returns.clip(upper=0).pow(2).mean()) * np.sqrt(252))
        annual_mean = float(returns.mean() * 252)
        cagr = terminal_nav ** (365.25 / elapsed_days) - 1 if terminal_nav > 0 else np.nan
        active = returns - pd.to_numeric(comparison["benchmark_return"], errors="coerce")
        tracking_error = float(active.std(ddof=0) * np.sqrt(252))
        prefix = nav_column.removesuffix("_nav")
        exposure = comparison.get(f"{prefix}_exposure")
        turnover = comparison.get(f"{prefix}_turnover")
        rows.append({
            "portfolio": label,
            "total_return": terminal_nav - 1,
            "cagr": cagr,
            "annualized_volatility": volatility,
            "max_drawdown": float(drawdown.min()),
            "sharpe_ratio": annual_mean / volatility if volatility > 1e-12 else np.nan,
            "sortino_ratio": annual_mean / downside if downside > 1e-12 else np.nan,
            "calmar_ratio": cagr / abs(drawdown.min()) if drawdown.min() < -1e-12 else np.nan,
            "tracking_error": tracking_error,
            "information_ratio": float(active.mean() * 252 / tracking_error) if tracking_error > 1e-12 else np.nan,
            "worst_daily_return": float(returns.min()),
            "average_exposure": float(exposure.mean()) if exposure is not None else np.nan,
            "annualized_turnover": float(turnover.sum() * 252 / len(returns)) if turnover is not None and len(returns) else np.nan,
            "sessions": len(returns),
        })
    return pd.DataFrame(rows)


def run_parameter_sweep(
    event_holdings: pd.DataFrame,
    prices: pd.DataFrame,
    benchmark_prices: pd.Series,
    base_spec: StrategySpec,
    top_n_values: tuple[int | None, ...] = (5, 10, 20, None),
    availability_models: tuple[str, ...] = ("filing_date",),
    execution_labels: tuple[str, ...] = tuple(EXECUTION_PROFILES),
    transaction_cost_bps_values: tuple[int | float, ...] = TRANSACTION_COST_BPS_OPTIONS,
    open_prices: pd.DataFrame | None = None,
    benchmark_open_prices: pd.Series | None = None,
    evaluation_window: tuple | None = None,
) -> pd.DataFrame:
    """Run a grid of plausible execution, breadth, and cost assumptions."""
    rows: list[dict[str, object]] = []
    manager_events = event_holdings[event_holdings["manager_code"] == base_spec.manager_code].copy()
    availability_labels = {value: label for label, value in AVAILABILITY_MODELS.items()}
    for top_n, availability_model, execution_label, transaction_cost_bps in product(
        top_n_values, availability_models, execution_labels, transaction_cost_bps_values,
    ):
        execution = EXECUTION_PROFILES[execution_label]
        spec = replace(
            base_spec,
            top_n=top_n,
            availability_model=availability_model,
            execution_timing=execution["execution_timing"],
            execution_delay_sessions=execution["execution_delay_sessions"],
            transaction_cost_bps=float(transaction_cost_bps),
        )
        try:
            comparison, coverage = run_strategy_comparison(
                manager_events, prices, benchmark_prices, spec, open_prices=open_prices,
                benchmark_open_prices=benchmark_open_prices,
            )
        except (PriceDataError, ValueError) as exc:
            rows.append({"manager_code": spec.manager_code, "portfolio_size": _top_n_label(top_n),
                         "top_n": top_n if top_n is not None else "full", "execution": execution_label,
                         "transaction_cost_bps": transaction_cost_bps, "status": "invalid",
                         "error": str(exc), "cagr": np.nan, "minimum_coverage": np.nan})
            continue
        if evaluation_window is not None and not comparison.empty:
            comparison = full_period_comparison(comparison, *evaluation_window, calendar=benchmark_prices.index)
            execution_dates = pd.to_datetime(coverage["execution_date"])
            coverage = coverage.loc[execution_dates.between(*map(pd.Timestamp, evaluation_window))]
        if comparison.empty:
            continue
        metrics = performance_summary(comparison).set_index("portfolio")
        disclosed = metrics.loc["Disclosed top positions"]
        benchmark = metrics.loc["Benchmark buy-and-hold"]
        sector_balanced = metrics.loc["Sector-balanced baseline"]
        rows.append({
            "status": "valid",
            "manager_code": spec.manager_code,
            "portfolio_size": _top_n_label(top_n),
            "top_n": top_n if top_n is not None else "full",
            "availability": availability_labels.get(availability_model, availability_model),
            "availability_model": availability_model,
            "execution": execution_label,
            "execution_timing": execution["execution_timing"],
            "execution_delay_sessions": execution["execution_delay_sessions"],
            "transaction_cost_bps": float(transaction_cost_bps),
            "total_return": float(disclosed["total_return"]),
            "cagr": float(disclosed["cagr"]),
            "annualized_volatility": float(disclosed["annualized_volatility"]),
            "max_drawdown": float(disclosed["max_drawdown"]),
            "benchmark_cagr": float(benchmark["cagr"]),
            "excess_cagr": float(disclosed["cagr"] - benchmark["cagr"]),
            "sector_balanced_cagr": float(sector_balanced["cagr"]),
            "mean_coverage": float(coverage.loc[coverage.status.isin(["accepted", "rejected_low_coverage"]), "weight_coverage"].mean()),
            "minimum_coverage": float(coverage.loc[coverage.status.isin(["accepted", "rejected_low_coverage"]), "weight_coverage"].min()),
            "rejected_events": int(coverage.status.eq("rejected_low_coverage").sum()),
            "start_date": pd.to_datetime(comparison["date"]).iloc[0].date().isoformat(),
            "end_date": pd.to_datetime(comparison["date"]).iloc[-1].date().isoformat(),
            "sessions": int(len(comparison)),
        })
    return pd.DataFrame(rows).reset_index(drop=True) if rows else pd.DataFrame()
