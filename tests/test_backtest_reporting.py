import numpy as np
import pandas as pd
import pytest

from thirteenf.backtest import StrategySpec, common_backtest_window, full_period_comparison, performance_summary
from thirteenf.backtest_reporting import chart_assumptions, execution_steps


def comparison(returns):
    frame = pd.DataFrame({"date": pd.bdate_range("2020-12-29", periods=len(returns))})
    for name in ("disclosed", "sector_balanced", "benchmark"):
        frame[f"{name}_return"] = returns if name != "benchmark" else 0.
        frame[f"{name}_nav"] = (1 + frame[f"{name}_return"]).cumprod()
    return frame


def test_risk_metrics_include_initial_loss_and_use_all_sessions_for_downside():
    frame = comparison([-.1, .2, -.05, .01])
    frame["disclosed_exposure"] = [.5, 1., 1., .5]
    frame["disclosed_turnover"] = [1., 0., 0., 1.]
    row = performance_summary(frame).iloc[0]
    volatility = np.std([-.1, .2, -.05, .01]) * np.sqrt(252)
    assert row.max_drawdown == pytest.approx(-.1)
    assert row.annualized_volatility == pytest.approx(volatility)
    assert row.sharpe_ratio == pytest.approx(.015 * 252 / volatility)
    assert row.sortino_ratio == pytest.approx(.015 * 252 / np.sqrt((.1**2 + .05**2) / 4 * 252))
    assert row.calmar_ratio == pytest.approx(row.cagr / .1)
    assert row.tracking_error == pytest.approx(volatility)
    assert row.information_ratio == pytest.approx(row.sharpe_ratio)
    assert row.average_exposure == .75
    assert row.annualized_turnover == 126
    assert row.worst_daily_return == -.1


def test_flat_returns_have_undefined_ratios():
    row = performance_summary(comparison([0.] * 5)).iloc[0]
    assert row.max_drawdown == 0
    assert row.annualized_volatility == 0
    for key in ("sharpe_ratio", "sortino_ratio", "calmar_ratio", "information_ratio"):
        assert pd.isna(row[key])


def test_window_metrics_rebase_returns_and_include_new_statistics():
    frame = comparison([.1, -.05, .01, .02, -.01, .03])
    result = performance_summary(full_period_comparison(frame, "2021-01-01", frame.date.max())).set_index("portfolio")
    later = result.loc["Disclosed top positions"]
    assert later.total_return == pytest.approx(1.02 * .99 * 1.03 - 1)
    assert later.sessions == 3
    assert later.worst_daily_return == -.01


def test_execution_guide_tracks_selected_scenario():
    spec = StrategySpec("DUQ", top_n=None, execution_timing="next_open", execution_delay_sessions=5,
                        transaction_cost_bps=25, benchmark="QQQ", minimum_coverage=.95)
    text = chart_assumptions(spec)
    assert "Full disclosed book" in text
    assert "Next open + 5 sessions" in text
    assert "25 bps" in text and "95%" in text and "QQQ" in text
    guide = " ".join(execution_steps(spec))
    assert "0.50%" in guide and "UTC" in guide and "252" in guide


def test_all_funds_use_intersection_of_available_history():
    first = comparison([.01] * 8)
    second = first.iloc[2:7].copy()
    third = first.iloc[1:6].copy()
    start, end = common_backtest_window({"A": first, "B": second, "C": third})
    assert start == first.date.iloc[2]
    assert end == first.date.iloc[5]
    for history in (first, second, third):
        result = full_period_comparison(history, start, end)
        assert len(result) == 4
        assert result.disclosed_nav.iloc[-1] == pytest.approx(1.01 ** 4)
    with pytest.raises(ValueError, match="Every fund"):
        common_backtest_window({"A": first, "B": first.iloc[:0]})


def test_delayed_first_execution_preserves_initial_cash_sessions():
    frame = comparison([.01] * 8)
    result = full_period_comparison(frame.iloc[3:], frame.date.min(), frame.date.max(), calendar=frame.date)
    assert len(result) == 8
    assert result.disclosed_return.iloc[:3].eq(0).all()
    assert result.benchmark_return.iloc[:3].eq(0).all()
    assert result.disclosed_nav.iloc[-1] == pytest.approx(1.01 ** 5)
