from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

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


def build_backtest_comparison_chart(comparison: pd.DataFrame, title: str, benchmark_label: str = "SPY", assumptions: str = "") -> object:
    """Plot disclosed strategy, sector-balanced baseline, and benchmark NAV."""
    labels = {
        "disclosed_nav": "Disclosed top positions",
        "sector_balanced_nav": "Sector-balanced baseline",
        "benchmark_nav": f"{benchmark_label} buy-and-hold",
    }
    available = [column for column in labels if column in comparison.columns]
    if comparison.empty or not available:
        return px.line(pd.DataFrame({"date": [], "portfolio": [], "nav": []}), x="date", y="nav", color="portfolio", title=title)
    data = comparison[["date", *available]].copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.melt("date", var_name="portfolio", value_name="nav")
    data["portfolio"] = data["portfolio"].map(labels)
    figure = px.line(data, x="date", y="nav", color="portfolio", title=title,
                     color_discrete_sequence=["#137C8B", "#8B6BB1", "#D69235"])
    figure.update_layout(
        xaxis_title="Date",
        yaxis_title="Growth of $1",
        hovermode="x unified",
        template="plotly_white",
        legend_title_text="Portfolio",
    )
    if assumptions:
        figure.update_layout(
            height=620,
            margin=dict(t=80, b=165),
            legend=dict(orientation="h", x=1, xanchor="right", y=-0.17, yanchor="top"),
            legend_title_text="",
        )
        figure.add_annotation(
            text=assumptions, x=0, y=-0.34, xref="paper", yref="paper",
            xanchor="left", yanchor="top", showarrow=False, align="left",
            font=dict(size=11, color="#526579"),
        )
    return figure


def build_backtest_sweep_distribution_chart(sweep: pd.DataFrame, title: str) -> object:
    """Show the return distribution across backtest assumptions."""
    if sweep.empty:
        return px.histogram(pd.DataFrame({"cagr": []}), x="cagr", title=title)
    figure = px.histogram(
        sweep.copy(),
        x="cagr",
        color="portfolio_size",
        nbins=24,
        marginal="box",
        title=title,
        labels={"cagr": "CAGR", "portfolio_size": "Portfolio"},
    )
    figure.update_layout(
        template="plotly_white",
        bargap=0.05,
        legend_title_text="Portfolio size",
        xaxis_tickformat=".0%",
        yaxis_title="Scenario count",
    )
    return figure


def build_backtest_sweep_scatter_chart(sweep: pd.DataFrame, title: str) -> object:
    """Plot return versus drawdown for the tested assumption grid."""
    if sweep.empty:
        return px.scatter(pd.DataFrame({"max_drawdown": [], "cagr": []}), x="max_drawdown", y="cagr", title=title)
    figure = px.scatter(
        sweep.copy(),
        x="max_drawdown",
        y="cagr",
        color="transaction_cost_bps",
        symbol="portfolio_size",
        hover_data=["availability", "execution", "mean_coverage", "minimum_coverage", "total_return"],
        title=title,
        labels={
            "max_drawdown": "Maximum drawdown",
            "cagr": "CAGR",
            "transaction_cost_bps": "Cost bps",
            "portfolio_size": "Portfolio",
        },
    )
    figure.update_layout(template="plotly_white", legend_title_text="Scenario")
    figure.update_xaxes(tickformat=".0%")
    figure.update_yaxes(tickformat=".0%")
    return figure



def build_monitor_sector_change_chart(
    alerts: pd.DataFrame, title: str, *, sort_by: str = "Largest change",
    focus_sector: str | None = None,
) -> object:
    """One bubble per sector row: change on X, portfolio share as bubble area."""
    figure = go.Figure()
    if alerts.empty:
        return figure.update_layout(title=title, template="plotly_white")
    if alerts["fund"].nunique() != 1 or alerts["quarter"].nunique() != 1:
        raise ValueError("Select one fund and report quarter for the sector rotation chart.")
    data = alerts.copy()
    data["_magnitude"] = data["change_pp"].abs()
    ordering = {
        "Largest change": (["_magnitude", "current_weight", "sector"], [False, False, True]),
        "Largest allocation": (["current_weight", "_magnitude", "sector"], [False, False, True]),
        "Sector name": (["sector"], [True]),
    }
    if sort_by not in ordering:
        raise ValueError(f"Unknown sector ordering: {sort_by}")
    columns, ascending = ordering[sort_by]
    data = data.sort_values(columns, ascending=ascending).reset_index(drop=True)
    extent = max(float(data["_magnitude"].max()) * 1.3, 0.5)
    teal, coral, neutral = "#0e9f8a", "#e68170", "#94a3b8"
    colors = [teal if change >= .005 else coral if change <= -.005 else neutral
              for change in data["change_pp"]]
    opacity = [1.0 if focus_sector is None or sector == focus_sector else .18 for sector in data["sector"]]
    # A separate row prevents labels or bubbles from overlapping even when
    # several sectors have identical weights and changes.
    for row in data.index:
        if row % 2 == 0:
            figure.add_shape(type="rect", xref="paper", x0=0, x1=1,
                             y0=row - .5, y1=row + .5, fillcolor="#f8fafc",
                             line_width=0, layer="below")
    figure.add_vline(x=0, line_color="#cbd5e1", line_dash="dot", line_width=1)
    details = []
    for item in data.itertuples():
        relative = (f"{item.change_pp / item.previous_weight * 100:+.1f}% of prior allocation"
                    if item.previous_weight > 0 else "New allocation")
        details.append([item.sector, item.previous_weight, item.current_weight, relative,
                        item.prior_quarter, str(item.accepted_at)])
    figure.add_trace(go.Scatter(
        x=data["change_pp"].tolist(), y=data.index.tolist(), mode="markers",
        name="Sectors", showlegend=False,
        marker=dict(
            size=data["current_weight"].clip(lower=0.01).tolist(), sizemode="area",
            # Fixed scale across funds and quarters: a 25% allocation always
            # has the same area. Small/zero weights retain a visible minimum.
            sizeref=2 * 100 / 54 ** 2, sizemin=5,
            symbol=["circle-open" if value == 0 else "circle" for value in data["current_weight"]],
            color=colors, opacity=opacity, line=dict(color="white", width=1.5),
        ),
        customdata=details,
        hovertemplate=(
            "<b>%{customdata[0]}</b>"
            "<br>Portfolio share: %{customdata[1]:.2f}% to %{customdata[2]:.2f}%"
            "<br>Change: %{x:+.2f} pp<br>%{customdata[3]}"
            "<br>Prior report: %{customdata[4]}<br>Accepted: %{customdata[5]}<extra></extra>"
        ),
    ))
    for row, item in data.iterrows():
        change = float(item["change_pp"])
        change_text = "0.00 pp" if abs(change) < .005 else f"{change:+.2f} pp"
        for x, value, color in (
            (.66, f"{item['previous_weight']:.2f}%", "#64748b"),
            (.81, f"<b>{item['current_weight']:.2f}%</b>", "#0f2940"),
            (1.0, f"<b>{change_text}</b>", colors[row]),
        ):
            figure.add_annotation(x=x, xref="paper", y=row, text=value, showarrow=False,
                                  xanchor="right", font=dict(size=12, color=color), opacity=opacity[row])
    for x, label in ((.66, "PRIOR"), (.81, "NOW"), (1.0, "CHANGE")):
        figure.add_annotation(x=x, xref="paper", y=1.075, yref="paper", text=label,
                              showarrow=False, xanchor="right", font=dict(size=10, color="#64748b"))
    for color, label in ((coral, "Reduced"), (neutral, "Unchanged"), (teal, "Increased")):
        figure.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=label,
                                   marker=dict(color=color, size=8), hoverinfo="skip"))
    labels = data["sector"].replace({
        "Information Technology": "Information<br>Technology",
        "Consumer Discretionary": "Consumer<br>Discretionary",
        "Communication Services": "Communication<br>Services",
    }).tolist()
    figure.update_layout(
        title=dict(text=title, x=.03, font=dict(size=19, color="#0f2940")),
        template="plotly_white", paper_bgcolor="white", plot_bgcolor="white",
        height=max(340, 190 + 52 * len(data)),
        margin=dict(t=110, r=25, b=80, l=155),
        font=dict(family="Inter, Segoe UI, sans-serif", color="#64748b", size=12),
        hoverlabel=dict(bgcolor="#142d40", font_color="white", bordercolor="#142d40"),
        legend=dict(orientation="h", x=1, y=1.2, xanchor="right", yanchor="bottom", font_size=11),
        xaxis=dict(title="Allocation change (pp)", domain=[0,.49], range=[-extent, extent],
                   ticksuffix="", nticks=5, showgrid=False, zeroline=False, fixedrange=True,
                   tickfont=dict(size=10)),
        yaxis=dict(title=None, range=[len(data) - .5, -.5], tickvals=data.index.tolist(),
                   ticktext=labels, showgrid=False, zeroline=False, fixedrange=True,
                   tickfont=dict(size=12, color="#334155")),
    )
    return figure


def build_combined_positioning_chart(
    positioning: pd.DataFrame,
    weight_column: str,
    title: str,
    top_n: int = 20,
) -> object:
    """Plot the largest positions in a multi-manager disclosed-book composite."""
    label = (
        "Equal-manager composite weight"
        if weight_column == "equal_manager_weight"
        else "Combined disclosed-value weight"
    )
    if positioning.empty:
        return px.bar(pd.DataFrame({"asset": [], weight_column: []}), x=weight_column, y="asset", title=title)
    data = positioning.nlargest(top_n, weight_column).sort_values(weight_column).copy()
    figure = px.bar(
        data,
        x=weight_column,
        y="asset",
        color="sector",
        orientation="h",
        custom_data=["fund_count", "managers_reporting", "held_by", "combined_disclosed_value"],
        color_discrete_map=SECTOR_COLORS,
        category_orders={"sector": SECTOR_ORDER},
        labels={weight_column: label, "asset": "Asset", "sector": "Sector"},
        title=title,
    )
    figure.update_traces(
        hovertemplate=(
            "Asset=%{y}<br>Weight=%{x:.2f}%<br>Managers=%{customdata[0]}/%{customdata[1]}"
            "<br>Disclosed value=$%{customdata[3]:,.0f}<br>Held by=%{customdata[2]}<extra></extra>"
        )
    )
    figure.update_layout(
        template="plotly_white",
        height=max(500, 28 * len(data) + 150),
        legend_title_text="Sector",
        margin=dict(t=70, r=30, b=60, l=120),
    )
    return figure

def build_combined_sector_snapshot_chart(
    positioning: pd.DataFrame,
    weight_column: str,
    title: str,
) -> object:
    """Plot a single-quarter all-manager sector allocation."""
    label = (
        "Equal-manager composite weight"
        if weight_column == "equal_manager_weight"
        else "Combined disclosed-value weight"
    )
    if positioning.empty:
        return px.bar(pd.DataFrame({"sector": [], weight_column: []}), x="sector", y=weight_column, title=title)
    data = positioning.groupby("sector", as_index=False)[weight_column].sum().sort_values(weight_column, ascending=False)
    figure = px.bar(
        data,
        x="sector",
        y=weight_column,
        color="sector",
        color_discrete_map=SECTOR_COLORS,
        category_orders={"sector": SECTOR_ORDER},
        labels={weight_column: label, "sector": "Sector"},
        title=title,
    )
    figure.update_traces(hovertemplate="Sector=%{x}<br>Weight=%{y:.2f}%<extra></extra>")
    figure.update_layout(template="plotly_white", showlegend=False, height=470)
    figure.update_xaxes(tickangle=-35)
    return figure
