from __future__ import annotations

import pandas as pd
import plotly.express as px


def build_sector_rotation_chart(rotation_df: pd.DataFrame, fund: str | None = None) -> object:
    """Plot quarter on X and disclosed portfolio weight on Y for one manager."""
    data = rotation_df.copy()
    if fund is not None and not data.empty:
        data = data[data["fund"] == fund]
    if data.empty:
        return px.line(pd.DataFrame({"quarter": [], "sector": [], "portfolio_weight": []}), x="quarter", y="portfolio_weight", color="sector")
    if fund is None and data["fund"].nunique() > 1:
        return px.line(
            data, x="quarter", y="portfolio_weight", color="sector", facet_row="fund",
            markers=True, title="Quarterly disclosed-book sector weights",
        )
    figure = px.line(data, x="quarter", y="portfolio_weight", color="sector", markers=True, title="Quarterly disclosed-book sector weights")
    figure.update_layout(xaxis_title="Quarter", yaxis_title="Portfolio Weight (%)", template="plotly_white")
    return figure


def build_overall_sector_rotation_chart(overall_df: pd.DataFrame, weighting: str) -> object:
    """Plot the combined quarterly sector composition as a stacked area."""
    data = overall_df.copy()
    title = (
        "Overall sector allocation — equal-weight managers"
        if weighting == "equal_manager"
        else "Overall sector allocation — combined disclosed value"
    )
    if data.empty:
        return px.area(
            pd.DataFrame({"quarter": [], "sector": [], "portfolio_weight": []}),
            x="quarter", y="portfolio_weight", color="sector", title=title,
        )
    figure = px.area(
        data,
        x="quarter",
        y="portfolio_weight",
        color="sector",
        custom_data=["manager_count"],
        title=title,
    )
    figure.update_traces(
        hovertemplate=(
            "Quarter=%{x}<br>Sector=%{fullData.name}<br>Weight=%{y:.2f}%"
            "<br>Managers=%{customdata[0]}<extra></extra>"
        )
    )
    figure.update_layout(
        xaxis_title="Quarter",
        yaxis_title="Aggregate Weight (%)",
        yaxis_range=[0, 100],
        hovermode="x unified",
        template="plotly_white",
    )
    return figure


def build_backtest_comparison_chart(comparison: pd.DataFrame, title: str) -> object:
    """Plot disclosed strategy, sector-balanced baseline, and SPY NAV."""
    labels = {
        "disclosed_nav": "Disclosed top positions",
        "sector_balanced_nav": "Sector-balanced baseline",
        "benchmark_nav": "SPY buy-and-hold",
    }
    available = [column for column in labels if column in comparison.columns]
    if comparison.empty or not available:
        return px.line(pd.DataFrame({"date": [], "portfolio": [], "nav": []}), x="date", y="nav", color="portfolio", title=title)
    data = comparison[["date", *available]].copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.melt("date", var_name="portfolio", value_name="nav")
    data["portfolio"] = data["portfolio"].map(labels)
    figure = px.line(data, x="date", y="nav", color="portfolio", title=title)
    figure.update_layout(
        xaxis_title="Date",
        yaxis_title="Growth of $1",
        hovermode="x unified",
        template="plotly_white",
        legend_title_text="Portfolio",
    )
    return figure
