from __future__ import annotations

import pandas as pd
import streamlit as st

from thirteenf.sec_live import filing_html_url

from thirteenf.filing_monitor import (
    SHORT_TERM_MANAGER_CODES,
    build_position_change_alerts,
    build_sector_change_alerts,
)
from thirteenf.visuals import (
    build_monitor_sector_change_chart,
)


@st.cache_data(show_spinner=False)
def _monitor_payload_cached(
    snapshot: pd.DataFrame,
    position_threshold_pp: float,
    sector_threshold_pp: float,
    quarters: int,
) -> dict[str, pd.DataFrame]:
    sector_changes = build_sector_change_alerts(snapshot, threshold_pp=0.0, quarters=quarters)
    return {
        "position_alerts": build_position_change_alerts(
            snapshot, threshold_pp=position_threshold_pp, quarters=quarters,
        ),
        "sector_alerts": sector_changes[sector_changes["change_pp"].abs().ge(sector_threshold_pp)].copy(),
        "sector_changes": sector_changes,
    }


def _accepted_text(values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce", utc=True)
    return parsed.dt.strftime("%Y-%m-%d %H:%M:%S UTC").fillna("Unknown")


def _with_filing_links(frame: pd.DataFrame) -> pd.DataFrame:
    """Use HTML for readers and retain the XML URL as explicit provenance."""
    result = frame.rename(columns={"source_url": "source_xml_url"}).copy()
    result["filing_url"] = result["source_xml_url"].map(filing_html_url)
    return result


def _download_table(label: str, frame: pd.DataFrame, filename: str, key: str) -> None:
    st.download_button(
        label,
        frame.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
        key=key,
    )


def _latest_short_term_filings(snapshot: pd.DataFrame) -> pd.DataFrame:
    data = snapshot[snapshot["manager_code"].isin(SHORT_TERM_MANAGER_CODES)].copy()
    if data.empty:
        return pd.DataFrame(columns=["manager", "report_period", "accepted_at", "source_xml_url", "filing_url"])
    data["report_period"] = pd.to_datetime(data["report_period"], errors="coerce")
    accepted = pd.Series(pd.NaT, index=data.index, dtype="datetime64[ns, UTC]")
    for column in ("acceptance_datetime", "available_at", "filing_date"):
        if column in data:
            accepted = accepted.fillna(pd.to_datetime(data[column], errors="coerce", utc=True))
    data["accepted_at"] = accepted
    data = data.sort_values(["manager_code", "report_period", "accepted_at"])
    result = (
        data.groupby("manager_code", as_index=False)
        .tail(1)[["manager_code", "fund", "report_period", "accepted_at", "source_url"]]
        .rename(columns={"fund": "manager"})
        .sort_values("accepted_at", ascending=False)
        .reset_index(drop=True)
    )
    result["report_period"] = result["report_period"].dt.strftime("%Y-%m-%d")
    result["accepted_at"] = _accepted_text(result["accepted_at"])
    return _with_filing_links(result)


def _render_position_alerts(alerts: pd.DataFrame) -> None:
    st.markdown("#### Short-term fund position changes")
    st.caption(
        "Each row compares one accepted quarterly disclosure with that manager's prior accepted disclosure. "
        "Full exits are always shown, even when the exited position was below the materiality threshold."
    )
    if alerts.empty:
        st.success("No position changes met the selected threshold in this window.")
        return

    managers = alerts[["manager_code", "fund"]].drop_duplicates().set_index("manager_code")["fund"].to_dict()
    left, right = st.columns(2)
    selected_managers = left.multiselect(
        "Short-term managers",
        list(managers),
        default=list(managers),
        format_func=lambda code: managers[code],
        key="monitor_managers",
    )
    change_types = alerts["change_type"].drop_duplicates().tolist()
    selected_changes = right.multiselect(
        "Position alert types",
        change_types,
        default=change_types,
        key="monitor_change_types",
    )
    sort_mode = st.radio(
        "Order position alerts by",
        ["Most recent", "Largest absolute change"],
        horizontal=True,
        key="monitor_position_sort",
    )
    visible = alerts[
        alerts["manager_code"].isin(selected_managers)
        & alerts["change_type"].isin(selected_changes)
    ].copy()
    visible["_magnitude"] = visible["change_pp"].abs()
    if sort_mode == "Largest absolute change":
        visible = visible.sort_values(["_magnitude", "accepted_at"], ascending=[False, False])
    else:
        visible = visible.sort_values(["accepted_at", "_magnitude"], ascending=[False, False])
    visible = _with_filing_links(visible.drop(columns="_magnitude"))
    visible["accepted_at"] = _accepted_text(visible["accepted_at"])
    display_columns = [
        "accepted_at", "quarter", "prior_quarter", "fund", "change_type", "asset", "sector",
        "previous_weight", "current_weight", "change_pp", "current_value_usd", "filing_url",
    ]
    st.dataframe(
        visible[display_columns],
        width="stretch",
        height=520,
        hide_index=True,
        column_config={
            "accepted_at": st.column_config.TextColumn("Accepted at"),
            "quarter": st.column_config.TextColumn("Quarter"),
            "prior_quarter": st.column_config.TextColumn("Prior quarter"),
            "fund": st.column_config.TextColumn("Manager", width="large"),
            "change_type": st.column_config.TextColumn("Alert"),
            "asset": st.column_config.TextColumn("Asset"),
            "sector": st.column_config.TextColumn("Sector", width="medium"),
            "previous_weight": st.column_config.NumberColumn("Previous weight", format="%.2f%%"),
            "current_weight": st.column_config.NumberColumn("Current weight", format="%.2f%%"),
            "change_pp": st.column_config.NumberColumn("Change", format="%+.2f pp"),
            "current_value_usd": st.column_config.NumberColumn("Current disclosed value", format="$%,.0f"),
            "filing_url": st.column_config.LinkColumn("SEC filing", display_text="Open filing"),
        },
    )
    _download_table("Download position alerts", visible, "short_term_position_alerts.csv", "download_position_alerts")


def _render_sector_alerts(alerts: pd.DataFrame, *, sector_changes: pd.DataFrame, all_funds: bool = False) -> None:
    st.markdown("#### Sector rotation" if all_funds else "#### Short-term fund sector rotation")
    st.caption(
        "Changes are measured in disclosed portfolio-weight percentage points. Unknown-sector holdings are "
        "excluded so mapping gaps are not presented as an investment sector."
    )
    chart_alerts = sector_changes if all_funds else sector_changes[sector_changes["manager_code"].ne("THIEL")]
    if not all_funds:
        st.caption("Thiel Macro is omitted from the chart because its sector history is sparse.")
    st.caption(
        "Each row is a sector. Left means reduced allocation; right means increased allocation. "
        "Bubble area shows its current share of the whole portfolio. Prior, Now and Change give the exact values."
    )
    if chart_alerts.empty:
        st.info("No comparable sector disclosures are available in this window.")
    else:
        prefix = "research" if all_funds else "monitor"
        left, right = st.columns(2)
        sort_by = left.selectbox(
            "Order sectors by", ["Largest change", "Largest allocation", "Sector name"],
            key=f"{prefix}_sector_order",
        )
        focus_options = ["All sectors", *sorted(chart_alerts["sector"].unique())]
        focus = right.selectbox(
            "Highlight a sector", focus_options, key=f"{prefix}_sector_focus",
            help="Highlight the same category across funds while keeping all other sectors visible.",
        )
        for manager_code, manager_alerts in chart_alerts.groupby("manager_code", sort=True):
            fund = manager_alerts["fund"].iloc[0]
            st.markdown(f"#### {fund}")
            quarters = sorted(manager_alerts["quarter"].unique(), key=lambda q: pd.Period(q, freq="Q"))
            quarter = st.selectbox(
                f"Report quarter - {fund}", quarters, index=len(quarters) - 1,
                key=f"{prefix}_sector_quarter_{manager_code}",
            )
            selected = manager_alerts[manager_alerts["quarter"].eq(quarter)]
            increases = selected[selected["change_pp"].gt(0)]
            decreases = selected[selected["change_pp"].lt(0)]
            highlights = []
            if not increases.empty:
                item = increases.loc[increases["change_pp"].idxmax()]
                highlights.append(f"Largest increase: {item['sector']} +{item['change_pp']:.2f} pp (now {item['current_weight']:.2f}%)")
            if not decreases.empty:
                item = decreases.loc[decreases["change_pp"].idxmin()]
                highlights.append(f"Largest reduction: {item['sector']} {item['change_pp']:.2f} pp (now {item['current_weight']:.2f}%)")
            st.caption(" | ".join(highlights) if highlights else "Sector allocations are unchanged.")
            if focus != "All sectors" and focus not in set(selected["sector"]):
                st.caption(f"{focus} has no current or prior allocation in this comparison.")
            st.plotly_chart(
                build_monitor_sector_change_chart(
                    selected, f"Sector allocation | {quarter}", sort_by=sort_by,
                    focus_sector=None if focus == "All sectors" else focus,
                ),
                width="stretch", theme=None, config={"displayModeBar": False},
                key=f"{prefix}_sector_bubbles_{manager_code}",
            )
            st.caption(
                f"{len(selected)} sectors shown. Bubble sizes use the same portfolio-share scale across funds. "
                "Tiny allocations have a minimum marker size; an outlined circle means a full exit. "
                "The alert threshold filters only the table below."
            )
    st.markdown("#### Material sector alerts")
    if alerts.empty:
        st.info("No sector changes meet the table threshold. All sectors remain visible in the charts.")
    visible = _with_filing_links(alerts)
    visible["accepted_at"] = _accepted_text(visible["accepted_at"])
    st.dataframe(
        visible[
            ["accepted_at", "quarter", "prior_quarter", "fund", "sector", "previous_weight", "current_weight", "change_pp", "filing_url"]
        ],
        width="stretch",
        height=430,
        hide_index=True,
        column_config={
            "accepted_at": st.column_config.TextColumn("Accepted at"),
            "quarter": st.column_config.TextColumn("Quarter"),
            "prior_quarter": st.column_config.TextColumn("Prior quarter"),
            "fund": st.column_config.TextColumn("Manager", width="large"),
            "sector": st.column_config.TextColumn("Sector", width="medium"),
            "previous_weight": st.column_config.NumberColumn("Previous weight", format="%.2f%%"),
            "current_weight": st.column_config.NumberColumn("Current weight", format="%.2f%%"),
            "change_pp": st.column_config.NumberColumn("Change", format="%+.2f pp"),
            "filing_url": st.column_config.LinkColumn("SEC filing", display_text="Open filing"),
        },
    )
    prefix = "all_funds" if all_funds else "short_term"
    _download_table("Download sector alerts", visible, f"{prefix}_sector_alerts.csv", f"{prefix}_download_sector_alerts")


def _sector_alert_settings(key_prefix: str) -> tuple[float, int]:
    left, right = st.columns(2)
    threshold = left.slider(
        "Alert table threshold (pp)", 0.5, 25.0, 5.0, 0.5,
        help="Filters the alert table by absolute weight change. Charts always include every relevant sector.",
        key=f"{key_prefix}_sector_threshold",
    )
    quarters = right.slider(
        "Recent quarters", 2, 12, 8, 1,
        help="Number of report quarters included in sector alerts and the bubble charts.",
        key=f"{key_prefix}_lookback",
    )
    return threshold, quarters


@st.cache_data(show_spinner=False)
def _all_fund_sector_alerts(snapshot: pd.DataFrame, threshold: float, quarters: int) -> pd.DataFrame:
    return build_sector_change_alerts(
        snapshot, threshold_pp=threshold, quarters=quarters,
        manager_codes=tuple(snapshot["manager_code"].dropna().unique()),
    )


def render_sector_research_changes(snapshot: pd.DataFrame) -> None:
    with st.expander("Sector change settings", expanded=False):
        threshold, quarters = _sector_alert_settings("research")
    sector_changes = _all_fund_sector_alerts(snapshot, 0.0, quarters)
    alerts = sector_changes[sector_changes["change_pp"].abs().ge(threshold)].copy()
    _render_sector_alerts(alerts, sector_changes=sector_changes, all_funds=True)


def render_filing_change_monitor(snapshot: pd.DataFrame, section: str = "Asset Changes") -> None:
    """Render the selected filing intelligence view."""
    st.caption(
        "Track quarterly asset and sector changes for Duquesne, Appaloosa and Thiel Macro. "
        "Alerts refresh when the saved SEC snapshot is updated."
    )
    with st.expander("Alert settings", expanded=False):
        if section == "Sector changes":
            sector_threshold, lookback_quarters = _sector_alert_settings("monitor")
            position_threshold = 5.0
        else:
            first, second = st.columns(2)
            position_threshold = first.slider(
                "Asset weight change (pp)", 0.5, 25.0, 5.0, 0.5,
                help="Absolute change in disclosed portfolio weight, measured in percentage points.",
                key="monitor_position_threshold",
            )
            lookback_quarters = second.slider(
                "Recent quarters", 2, 12, 8, 1,
                help="Number of report quarters included in alert tables.",
                key="monitor_asset_lookback",
            )
            sector_threshold = 5.0

    with st.spinner("Comparing accepted SEC disclosures..."):
        payload = _monitor_payload_cached(
            snapshot,
            position_threshold,
            sector_threshold,
            lookback_quarters,
        )
    position_alerts = payload["position_alerts"]
    sector_alerts = payload["sector_alerts"]

    latest_filings = _latest_short_term_filings(snapshot)
    latest_accepted = latest_filings["accepted_at"].iloc[0].split()[0] if not latest_filings.empty else "Unknown"
    summary = st.columns(3)
    summary[0].metric("Latest accepted date", latest_accepted)
    summary[1].metric("Position alerts", len(position_alerts))
    summary[2].metric("Sector alerts", len(sector_alerts))
    with st.expander("Latest short-term filings", expanded=False):
        st.dataframe(
            latest_filings.drop(columns="source_xml_url"),
            width="stretch",
            hide_index=True,
            column_config={
                "manager_code": st.column_config.TextColumn("Code"),
                "manager": st.column_config.TextColumn("Manager", width="large"),
                "report_period": st.column_config.TextColumn("Report period"),
                "accepted_at": st.column_config.TextColumn("Accepted at"),
                "filing_url": st.column_config.LinkColumn("SEC filing", display_text="Open filing"),
            },
        )

    if section == "Asset Changes":
        _render_position_alerts(position_alerts)
    elif section == "Sector changes":
        _render_sector_alerts(sector_alerts, sector_changes=payload["sector_changes"])

    st.info(
        "Interpretation: these are delayed, long-only disclosed-book changes. A new alert is a research prompt, "
        "not evidence that the manager still holds the position today or that the position was unhedged."
    )
