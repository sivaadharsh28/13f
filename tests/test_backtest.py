import pandas as pd
import pytest

from thirteenf.backtest import (
    StrategySpec, build_disclosed_book_signals,
    build_sector_balanced_baseline, filter_signals_for_price_coverage,
    performance_summary, run_event_backtest, run_parameter_sweep, run_strategy_comparison,
)


def test_signal_builder_excludes_options_and_normalizes_top_n():
    rows = pd.DataFrame([
        {"manager_code": "DUQ", "snapshot_accession": "A", "available_at": "2026-01-02T20:00:00Z", "ticker_clean": "AAPL", "market_value_usd": 60, "put_call": "", "report_period": "2025-12-31"},
        {"manager_code": "DUQ", "snapshot_accession": "A", "available_at": "2026-01-02T20:00:00Z", "ticker_clean": "MSFT", "market_value_usd": 40, "put_call": "", "report_period": "2025-12-31"},
        {"manager_code": "DUQ", "snapshot_accession": "A", "available_at": "2026-01-02T20:00:00Z", "ticker_clean": "NVDA", "market_value_usd": 500, "put_call": "Call", "report_period": "2025-12-31"},
    ])
    result = build_disclosed_book_signals(rows, StrategySpec("DUQ", top_n=2))
    assert set(result["ticker_clean"]) == {"AAPL", "MSFT"}
    assert result["target_weight"].sum() == 1.0


def test_backtest_waits_until_next_session_and_charges_turnover():
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
    prices = pd.DataFrame({"AAPL": [100.0, 110.0, 121.0]}, index=dates)
    benchmark = pd.Series([100.0, 100.0, 100.0], index=dates)
    signals = pd.DataFrame([{
        "available_at": "2026-01-02T20:00:00Z", "ticker_clean": "AAPL",
        "target_weight": 1.0, "max_holding_sessions": 63,
    }])
    result = run_event_backtest(signals, prices, benchmark, transaction_cost_bps=10)
    assert result.iloc[0]["strategy_return"] == 0.0
    assert result.iloc[1]["strategy_return"] == pytest.approx(-0.001)
    assert round(result.iloc[2]["strategy_return"], 10) == 0.1


def test_sector_balanced_baseline_has_equal_sector_budgets():
    signals = pd.DataFrame([
        {"available_at": "2026-01-01", "manager_code": "DUQ", "report_period": "2025-12-31", "ticker_clean": "A", "target_weight": .8},
        {"available_at": "2026-01-01", "manager_code": "DUQ", "report_period": "2025-12-31", "ticker_clean": "B", "target_weight": .1},
        {"available_at": "2026-01-01", "manager_code": "DUQ", "report_period": "2025-12-31", "ticker_clean": "C", "target_weight": .1},
    ])
    result = build_sector_balanced_baseline(signals, {"A": "Tech", "B": "Tech", "C": "Energy"})
    assert result.loc[result["sector"].eq("Tech"), "target_weight"].sum() == .5
    assert result.loc[result["sector"].eq("Energy"), "target_weight"].sum() == .5


def test_weights_drift_between_rebalances_instead_of_daily_rebalancing():
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])
    prices = pd.DataFrame({"A": [100.0, 100.0, 200.0, 200.0], "B": [100.0, 100.0, 100.0, 200.0]}, index=dates)
    benchmark = pd.Series(100.0, index=dates)
    signals = pd.DataFrame([
        {"available_at": "2026-01-02T20:00:00Z", "ticker_clean": "A", "target_weight": .5, "max_holding_sessions": 63},
        {"available_at": "2026-01-02T20:00:00Z", "ticker_clean": "B", "target_weight": .5, "max_holding_sessions": 63},
    ])
    result = run_event_backtest(signals, prices, benchmark, transaction_cost_bps=0)
    # After A doubles, its weight drifts from 50% to 2/3; B's next-day doubling
    # therefore earns 1/3, rather than the 1/2 from implicit daily rebalancing.
    assert round(result.iloc[-1]["strategy_return"], 8) == round(1 / 3, 8)


def test_price_coverage_is_measured_at_each_execution_date():
    dates = pd.to_datetime(["2026-01-02", "2026-01-05"])
    prices = pd.DataFrame({"A": [100.0, 101.0], "LATE": [float("nan"), float("nan")]}, index=dates)
    signals = pd.DataFrame([
        {"available_at": "2026-01-02T20:00:00Z", "ticker_clean": "A", "target_weight": .6},
        {"available_at": "2026-01-02T20:00:00Z", "ticker_clean": "LATE", "target_weight": .4},
    ])
    filtered, coverage = filter_signals_for_price_coverage(signals, prices, minimum_coverage=0.5)
    assert set(filtered["ticker_clean"]) == {"A"}
    assert filtered["target_weight"].sum() == .6
    assert coverage.iloc[0]["weight_coverage"] == .6


def test_full_book_signal_includes_all_common_equities():
    rows = pd.DataFrame([
        {"manager_code": "DUQ", "snapshot_accession": "A", "available_at": "2026-01-02T20:00:00Z", "ticker_clean": "A", "market_value_usd": 50, "put_call": "", "report_period": "2025-12-31"},
        {"manager_code": "DUQ", "snapshot_accession": "A", "available_at": "2026-01-02T20:00:00Z", "ticker_clean": "B", "market_value_usd": 30, "put_call": "", "report_period": "2025-12-31"},
        {"manager_code": "DUQ", "snapshot_accession": "A", "available_at": "2026-01-02T20:00:00Z", "ticker_clean": "C", "market_value_usd": 20, "put_call": "", "report_period": "2025-12-31"},
    ])
    result = build_disclosed_book_signals(rows, StrategySpec("DUQ", top_n=None))
    assert set(result["ticker_clean"]) == {"A", "B", "C"}
    assert result["target_weight"].sum() == 1.0


def test_execution_delay_waits_extra_trading_sessions():
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])
    prices = pd.DataFrame({"A": [100.0, 110.0, 121.0, 133.1]}, index=dates)
    benchmark = pd.Series(100.0, index=dates)
    signals = pd.DataFrame([{
        "available_at": "2026-01-02T20:00:00Z", "ticker_clean": "A",
        "target_weight": 1.0, "max_holding_sessions": 63,
    }])
    result = run_event_backtest(signals, prices, benchmark, transaction_cost_bps=0, execution_delay_sessions=1)
    assert result.iloc[1]["strategy_return"] == 0.0
    assert result.iloc[2]["strategy_return"] == 0.0
    assert round(result.iloc[3]["strategy_return"], 10) == 0.1


def test_next_open_uses_adjusted_open_to_close_return():
    dates = pd.to_datetime(["2026-01-02", "2026-01-05"])
    prices = pd.DataFrame({"A": [100.0, 110.0]}, index=dates)
    opens = pd.DataFrame({"A": [100.0, 105.0]}, index=dates)
    benchmark = pd.Series(100.0, index=dates)
    signals = pd.DataFrame([{
        "available_at": "2026-01-02T20:00:00Z", "ticker_clean": "A",
        "target_weight": 1.0, "max_holding_sessions": 63,
    }])
    result = run_event_backtest(
        signals, prices, benchmark, transaction_cost_bps=0, execution_timing="next_open", open_prices=opens, benchmark_open_prices=benchmark,
    )
    assert round(result.iloc[1]["strategy_return"], 10) == round(110 / 105 - 1, 10)


def test_next_open_requires_adjusted_open_prices():
    dates = pd.to_datetime(["2026-01-02", "2026-01-05"])
    prices = pd.DataFrame({"A": [100.0, 110.0]}, index=dates)
    benchmark = pd.Series(100.0, index=dates)
    signals = pd.DataFrame([{
        "available_at": "2026-01-02T20:00:00Z", "ticker_clean": "A",
        "target_weight": 1.0, "max_holding_sessions": 63,
    }])
    try:
        run_event_backtest(signals, prices, benchmark, transaction_cost_bps=0, execution_timing="next_open")
    except ValueError as exc:
        assert "adjusted open prices" in str(exc)
    else:
        raise AssertionError("next_open accepted missing open prices")


def test_parameter_sweep_returns_one_row_per_assumption_combination():
    rows = pd.DataFrame([
        {"manager_code": "DUQ", "snapshot_accession": "A", "available_at": "2026-01-02T20:00:00Z", "ticker_clean": "A", "market_value_usd": 60, "put_call": "", "report_period": "2025-12-31"},
        {"manager_code": "DUQ", "snapshot_accession": "A", "available_at": "2026-01-02T20:00:00Z", "ticker_clean": "B", "market_value_usd": 40, "put_call": "", "report_period": "2025-12-31"},
    ])
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
    prices = pd.DataFrame({"A": [100.0, 101.0, 102.0], "B": [100.0, 100.0, 100.0]}, index=dates)
    benchmark = pd.Series([100.0, 100.0, 100.0], index=dates)
    result = run_parameter_sweep(
        rows,
        prices,
        benchmark,
        StrategySpec("DUQ"),
        top_n_values=(1, None),
        availability_models=("filing_date",),
        execution_labels=("Next close",),
        transaction_cost_bps_values=(10, 25),
    )
    assert len(result) == 4
    assert set(result["portfolio_size"]) == {"Top 1", "Full disclosed book"}



def test_next_open_requires_adjusted_open_prices():
    dates = pd.to_datetime(["2026-01-02", "2026-01-05"])
    prices = pd.DataFrame({"A": [100.0, 110.0]}, index=dates)
    benchmark = pd.Series(100.0, index=dates)
    signals = pd.DataFrame([{
        "available_at": "2026-01-02T20:00:00Z", "ticker_clean": "A",
        "target_weight": 1.0, "max_holding_sessions": 63,
    }])
    try:
        run_event_backtest(signals, prices, benchmark, transaction_cost_bps=0, execution_timing="next_open")
    except ValueError as exc:
        assert "adjusted open prices" in str(exc)
    else:
        raise AssertionError("next_open accepted missing open prices")
