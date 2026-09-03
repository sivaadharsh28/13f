from __future__ import annotations

import pandas as pd
import plotly.express as px

from thirteenf.sector import SECTOR_COLORS, SECTOR_OPTIONS


SECTOR_ORDER = [*SECTOR_OPTIONS, "Unknown"]


def _quarter_order(values: pd.Series) -> list[str]:
    """Return 13F quarter labels in chronological rather than input order."""
    labels = values.dropna().astype(str).unique().tolist()
    return sorted(labels, key=lambda label: pd.Period(label, freq="Q").ordinal)


def _complete_sector_quarters(data: pd.DataFrame) -> pd.DataFrame:
    """Show a zero weight when a reported quarter has no holding in a sector."""
    quarters = _quarter_order(data["quarter"])
    sectors = [sector for sector in SECTOR_ORDER if sector in set(data["sector"])]
    if not quarters or not sectors:
        return data
    grouped = data.groupby(["quarter", "sector"], as_index=False)["portfolio_weight"].sum()
    complete = pd.MultiIndex.from_product(
        [quarters, sectors], names=["quarter", "sector"]
    ).to_frame(index=False)
    return complete.merge(grouped, on=["quarter", "sector"], how="left").fillna({"portfolio_weight": 0.0})


def _sector_layout(figure: object, *, yaxis_title: str, hovermode: str = "closest") -> object:
    """Apply a consistent readable layout to sector charts."""
    figure.update_layout(
        xaxis_title="Quarter",
        yaxis_title=yaxis_title,
        template="plotly_white",
        hovermode=hovermode,
        legend_title_text="Sector",
        legend=dict(orientation="h", yanchor="top", y=-0.28, xanchor="left", x=0),
        margin=dict(t=70, r=30, b=135, l=65),
        height=520,
    )
    figure.update_xaxes(type="category", tickangle=-45)
    figure.update_yaxes(ticksuffix="%")
    return figure


def build_sector_rotation_chart(rotation_df: pd.DataFrame, fund: str | None = None) -> object:
    """Plot quarter on X and disclosed portfolio weight on Y for one manager."""
    data = rotation_df.copy()
    if fund is not None and not data.empty:
        data = data[data["fund"] == fund]
    if data.empty:
        return px.line(
            pd.DataFrame({"quarter": [], "sector": [], "portfolio_weight": []}),
            x="quarter", y="portfolio_weight", color="sector",
            color_discrete_map=SECTOR_COLORS,
        )
    data = _complete_sector_quarters(data)
    figure = px.line(
        data,
        x="quarter",
        y="portfolio_weight",
        color="sector",
        markers=True,
        title="Quarterly disclosed-book sector weights",
        color_discrete_map=SECTOR_COLORS,
        category_orders={
            "quarter": _quarter_order(data["quarter"]),
            "sector": SECTOR_ORDER,
        },
    )
    figure.update_traces(
        hovertemplate="Quarter=%{x}<br>Sector=%{fullData.name}<br>Weight=%{y:.2f}%<extra></extra>"
    )
    return _sector_layout(figure, yaxis_title="Portfolio weight")


def build_overall_sector_rotation_chart(overall_df: pd.DataFrame, weighting: str) -> object:
    """Plot the combined quarterly sector composition as a stacked area."""
    data = overall_df.copy()
    title = (
        "Overall sector allocation - equal-weight managers"
        if weighting == "equal_manager"
        else "Overall sector allocation - combined disclosed value"
    )
    if data.empty:
        return px.area(
            pd.DataFrame({"quarter": [], "sector": [], "portfolio_weight": []}),
            x="quarter", y="portfolio_weight", color="sector", title=title,
            color_discrete_map=SECTOR_COLORS,
        )
    figure = px.area(
        data,
        x="quarter",
        y="portfolio_weight",
        color="sector",
        custom_data=["manager_count"],
        title=title,
        color_discrete_map=SECTOR_COLORS,
        category_orders={
            "quarter": _quarter_order(data["quarter"]),
            "sector": SECTOR_ORDER,
        },
    )
    figure.update_traces(
        hovertemplate=(
            "Quarter=%{x}<br>Sector=%{fullData.name}<br>Weight=%{y:.2f}%"
            "<br>Managers=%{customdata[0]}<extra></extra>"
        )
    )
    figure = _sector_layout(figure, yaxis_title="Aggregate weight", hovermode="x unified")
    figure.update_yaxes(range=[0, 100])
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
