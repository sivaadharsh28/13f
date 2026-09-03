from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from thirteenf.backtest import STRATEGY_SPECS, performance_summary
from thirteenf.config import PROCESSED_DATA_DIR, SEC_USER_AGENT_ENV, SECTOR_OVERRIDE_PATH
from thirteenf.dashboard import build_dashboard_data
from thirteenf.quarterly_data import build_quarterly_sector_rotation_window
from thirteenf.runner import run_sec_ingestion
from thirteenf.sector import (
    SECTOR_OPTIONS,
    apply_sector_overrides,
    build_overall_sector_rotation,
    load_sector_overrides,
    save_sector_overrides,
)
from thirteenf.storage import load_snapshot
from thirteenf.visuals import (
    build_backtest_comparison_chart,
    build_overall_sector_rotation_chart,
    build_sector_rotation_chart,
)


def _modified_ns(path: Path) -> int:
    return path.stat().st_mtime_ns if path.exists() else 0


@st.cache_data(show_spinner=False)
def _load_snapshot_cached(path_text: str, modified_ns: int) -> pd.DataFrame:
    _ = modified_ns
    return load_snapshot(path_text)


@st.cache_data(show_spinner=False)
def _load_sector_overrides_cached(path_text: str, modified_ns: int) -> pd.DataFrame:
    _ = modified_ns
    return load_sector_overrides(path_text)


@st.cache_data(show_spinner=False)
def _build_dashboard_payload(snapshot: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return build_dashboard_data(snapshot)


@st.cache_data(show_spinner=False)
def _build_rotation(snapshot: pd.DataFrame) -> pd.DataFrame:
    return build_quarterly_sector_rotation_window(holdings=snapshot)


@st.cache_data(show_spinner=False)
def _build_overall_rotation(snapshot: pd.DataFrame, weighting: str) -> pd.DataFrame:
    return build_overall_sector_rotation(snapshot, weighting=weighting)


@st.cache_data(show_spinner=False)
def _read_backtest_csv(path_text: str, modified_ns: int) -> pd.DataFrame:
    _ = modified_ns
    return pd.read_csv(path_text, parse_dates=["date"])


@st.cache_data(show_spinner=False)
def _read_coverage_csv(path_text: str, modified_ns: int) -> pd.DataFrame:
    _ = modified_ns
    return pd.read_csv(path_text)


@st.cache_data(show_spinner=False)
def _performance_summary_cached(comparison: pd.DataFrame) -> pd.DataFrame:
    return performance_summary(comparison)


def _app_secrets() -> tuple[str, str]:
    try:
        configured_user_agent = str(st.secrets.get(SEC_USER_AGENT_ENV, ""))
        refresh_setting = str(st.secrets.get("THIRTEENF_ENABLE_SEC_REFRESH", "false"))
    except Exception:
        configured_user_agent = ""
        refresh_setting = "false"
    configured_user_agent = os.getenv(SEC_USER_AGENT_ENV, configured_user_agent)
    refresh_setting = os.getenv("THIRTEENF_ENABLE_SEC_REFRESH", refresh_setting)
    return configured_user_agent, refresh_setting


def _load_snapshot() -> pd.DataFrame:
    data_path = PROCESSED_DATA_DIR / "sec_holdings_history.csv"
    if not data_path.exists():
        return pd.DataFrame()
    snapshot = _load_snapshot_cached(str(data_path), _modified_ns(data_path))
    overrides = _load_sector_overrides_cached(
        str(SECTOR_OVERRIDE_PATH),
        _modified_ns(SECTOR_OVERRIDE_PATH),
    )
    return apply_sector_overrides(snapshot, overrides)


def _unknown_position_summary(snapshot: pd.DataFrame) -> pd.DataFrame:
    columns = ["cusip", "ticker", "issuer", "latest_report", "reports", "disclosed_value_usd", "sector"]
    sector = snapshot.get("sector", pd.Series("", index=snapshot.index))
    unknown = snapshot[sector.eq("Unknown")].copy()
    if unknown.empty:
        return pd.DataFrame(columns=columns)
    unknown["cusip"] = unknown["cusip"].astype(str).str.strip().str.zfill(9)
    unknown["ticker"] = unknown.get("ticker_clean", unknown.get("ticker", "")).fillna("")
    unknown["issuer"] = unknown.get("issuer", "").fillna("")
    unknown["report_period"] = pd.to_datetime(unknown["report_period"], errors="coerce")
    unknown["market_value_usd"] = pd.to_numeric(unknown["market_value_usd"], errors="coerce").fillna(0.0)
    result = (
        unknown.groupby(["cusip", "ticker", "issuer"], dropna=False, as_index=False)
        .agg(
            latest_report=("report_period", "max"),
            reports=("report_period", "nunique"),
            disclosed_value_usd=("market_value_usd", "sum"),
        )
        .sort_values("disclosed_value_usd", ascending=False)
        .reset_index(drop=True)
    )
    result["latest_report"] = result["latest_report"].dt.strftime("%Y-%m-%d")
    result["sector"] = ""
    return result[columns]


def _render_sector_override_editor(snapshot: pd.DataFrame) -> None:
    with st.expander("Resolve unknown sector positions", expanded=False):
        unknown = _unknown_position_summary(snapshot)
        if unknown.empty:
            st.success("Every displayed security has a reviewed sector assignment.")
            return
        st.caption(
            "Assign a GICS sector by CUSIP. Saving applies the assignment to that security's "
            "full disclosed history and writes data/sector_overrides.csv locally."
        )
        edited = st.data_editor(
            unknown,
            width="stretch",
            hide_index=True,
            disabled=["cusip", "ticker", "issuer", "latest_report", "reports", "disclosed_value_usd"],
            column_config={
                "latest_report": st.column_config.TextColumn("Latest report"),
                "reports": st.column_config.NumberColumn("Reports", format="%d"),
                "disclosed_value_usd": st.column_config.NumberColumn("Disclosed value", format="$%.0f"),
                "sector": st.column_config.SelectboxColumn(
                    "Sector assignment",
                    options=list(SECTOR_OPTIONS),
                    required=False,
                    help="Choose the sector you have independently reviewed for this CUSIP.",
                ),
            },
            key="sector_override_editor",
        )
        selected = edited[edited["sector"].isin(SECTOR_OPTIONS)][["cusip", "sector"]]
        if st.button("Save assignments locally", disabled=selected.empty, key="save_sector_assignments"):
            try:
                save_sector_overrides(selected, SECTOR_OVERRIDE_PATH)
            except OSError as exc:
                st.error(f"Could not save local assignments: {exc}")
            else:
                st.cache_data.clear()
                st.success(
                    "Sector assignments saved. Commit data/sector_overrides.csv to GitHub so the "
                    "published app receives the same reviewed mappings."
                )
                st.rerun()
        template = unknown[["cusip", "ticker", "issuer", "sector"]]
        st.download_button(
            "Download assignment template",
            template.to_csv(index=False).encode("utf-8"),
            file_name="sector_overrides.csv",
            mime="text/csv",
            help="For a deployed app, edit this file locally, commit it, and push it to GitHub.",
        )


def _render_backtest_section(code: str, investor: str, fund_name: str) -> None:
    spec = STRATEGY_SPECS[code]
    st.markdown(f"#### {investor}-inspired disclosed-book strategy")
    rules = pd.DataFrame({
        "Rule": [
            "Signal", "Availability", "Execution", "Rebalance",
            "Maximum holding period", "Transaction costs", "Benchmark", "Sector baseline",
        ],
        "Definition": [
            f"Top {spec.top_n} reported common-equity positions, value weighted",
            "SEC acceptance timestamp, including later amendment events",
            "Close of the first trading session strictly after acceptance",
            "At each new filing event; otherwise weights drift with market returns",
            f"{spec.max_holding_sessions} trading sessions, then cash if no newer filing",
            f"{spec.transaction_cost_bps:.0f} bps per unit of one-way turnover",
            f"{spec.benchmark} buy-and-hold from the first executable signal",
            "Equal capital per represented sector, then equal weight within each sector",
        ],
    })
    st.dataframe(rules, width="stretch", hide_index=True)

    result_path = PROCESSED_DATA_DIR / f"backtest_{code.lower()}.csv"
    coverage_path = PROCESSED_DATA_DIR / f"backtest_{code.lower()}_coverage.csv"
    if not result_path.exists():
        st.info(
            "No persisted backtest result is available yet. Generate the point-in-time price "
            "snapshot and results with `python scripts/build_backtests.py`."
        )
        return
    try:
        comparison = _read_backtest_csv(str(result_path), _modified_ns(result_path))
    except Exception as exc:
        st.warning(
            "Backtest result is not readable yet. If `scripts/build_backtests.py` is still "
            f"running, wait for it to finish and refresh this page. Details: {exc}"
        )
        return
    if comparison.empty:
        st.warning("No executable signals had sufficient price data for this manager.")
        return

    st.plotly_chart(
        build_backtest_comparison_chart(comparison, f"{fund_name}: strategy comparison"),
        width="stretch",
    )
    metrics = _performance_summary_cached(comparison)
    st.dataframe(
        metrics.style.format({
            "total_return": "{:.1%}",
            "cagr": "{:.1%}",
            "annualized_volatility": "{:.1%}",
            "max_drawdown": "{:.1%}",
        }),
        width="stretch",
        hide_index=True,
    )
    if coverage_path.exists():
        try:
            coverage = _read_coverage_csv(str(coverage_path), _modified_ns(coverage_path))
        except Exception as exc:
            st.warning(f"Coverage diagnostics are not readable yet: {exc}")
            return
        mean_coverage = coverage["weight_coverage"].mean() if not coverage.empty else 0.0
        minimum_coverage = coverage["weight_coverage"].min() if not coverage.empty else 0.0
        st.caption(
            f"Executable price coverage of selected disclosed weight: mean {mean_coverage:.1%}; "
            f"worst event {minimum_coverage:.1%}."
        )
        if minimum_coverage < 0.90:
            st.warning(
                "At least one rebalance had under 90% original signal-price coverage. The remaining "
                "positions were renormalized, which can materially bias this result."
            )


def main() -> None:
    st.title("13F Disclosed-Book Research")
    st.caption("SEC Form 13F positions are delayed disclosures and exclude short positions and many non-13(f) assets.")

    configured_user_agent, refresh_setting = _app_secrets()
    refresh_enabled = refresh_setting.lower() == "true"

    if refresh_enabled and st.button("Refresh from SEC"):
        try:
            with st.spinner("Retrieving and reconciling SEC filings from 2014..."):
                run_sec_ingestion(
                    user_agent=configured_user_agent,
                    quarters=None,
                    start_date="2014-01-01",
                )
            st.cache_data.clear()
            st.success("SEC history refreshed.")
        except Exception as exc:
            st.error(f"Refresh failed: {exc}")
    elif not refresh_enabled:
        st.caption("SEC refresh is disabled in the web UI; publish reviewed data snapshots from the ingestion CLI.")

    try:
        snapshot = _load_snapshot()
    except Exception as exc:
        st.error(f"Saved data rejected: {exc}")
        snapshot = pd.DataFrame()

    if snapshot.empty:
        st.warning(
            f"No production SEC dataset is available. Set {SEC_USER_AGENT_ENV} and run "
            '`thirteenf --source sec --sec-user-agent "Organization email@example.com"`.'
        )
        st.stop()

    market_values = pd.to_numeric(
        snapshot.get("market_value_usd", pd.Series(0.0, index=snapshot.index)),
        errors="coerce",
    ).fillna(0.0)
    unknown_mask = snapshot.get("sector", pd.Series("Unknown", index=snapshot.index)).eq("Unknown")
    unmapped_value_share = market_values[unknown_mask].sum() / market_values.sum() if market_values.sum() else 0.0

    # The date metrics need wider columns; Streamlit otherwise truncates a
    # large metric value such as 2014-03-31 with an ellipsis.
    status_columns = st.columns([0.8, 1.45, 1.45, 1.3])
    first_report = pd.Timestamp(snapshot["report_period"].min()).strftime("%Y-%m-%d")
    latest_report = pd.Timestamp(snapshot["report_period"].max()).strftime("%Y-%m-%d")
    status_columns[0].metric("Managers", snapshot["manager_code"].nunique())
    status_columns[1].metric("First report", first_report)
    status_columns[2].metric("Latest report", latest_report)
    status_columns[3].metric("Unmapped disclosed value", f"{unmapped_value_share:.2%}")

    with st.spinner("Preparing dashboard data..."):
        payload = _build_dashboard_payload(snapshot)
        rotation = _build_rotation(snapshot)

    quarters = sorted(rotation["quarter"].dropna().unique()) if not rotation.empty else []
    if len(quarters) > 1:
        selected_quarters = st.select_slider(
            "Displayed quarter range",
            options=quarters,
            value=(quarters[0], quarters[-1]),
            help="Drag either endpoint to change the time window used by both sector charts.",
        )
        visible_rotation = rotation[rotation["quarter"].between(selected_quarters[0], selected_quarters[1])].copy()
    else:
        selected_quarters = (quarters[0], quarters[0]) if quarters else (None, None)
        visible_rotation = rotation

    funds = sorted(rotation["fund"].unique()) if not rotation.empty else []
    selected_fund = st.selectbox("Manager", funds) if funds else None

    st.subheader("Quarterly sector rotation")
    st.plotly_chart(build_sector_rotation_chart(visible_rotation, selected_fund), width="stretch")
    selected_rotation = visible_rotation[visible_rotation["fund"].eq(selected_fund)].copy()
    if not selected_rotation.empty:
        latest_quarter = selected_rotation["quarter"].max()
        latest_details = (
            selected_rotation[selected_rotation["quarter"].eq(latest_quarter)]
            .sort_values("portfolio_weight", ascending=False)
            .rename(columns={"sector": "Sector", "portfolio_weight": "Portfolio weight (%)"})
        )
        st.caption(f"Visible details: {selected_fund}, {latest_quarter}.")
        st.dataframe(
            latest_details[["Sector", "Portfolio weight (%)"]].style.format({"Portfolio weight (%)": "{:.2f}%"}),
            width="stretch",
            hide_index=True,
        )

    st.subheader("Overall quarterly sector allocation")
    weighting_label = st.radio(
        "Aggregation method",
        ["Equal-weight managers", "Combined disclosed value"],
        horizontal=True,
        help=(
            "Equal-weight managers gives each reporting fund the same influence. "
            "Combined disclosed value pools the reported dollar values and is dominated by larger 13F books."
        ),
    )
    weighting = "equal_manager" if weighting_label == "Equal-weight managers" else "disclosed_value"
    visible_snapshot = snapshot.copy()
    if selected_quarters[0] is not None:
        visible_snapshot["_quarter"] = pd.PeriodIndex(pd.to_datetime(visible_snapshot["report_period"]), freq="Q").astype(str)
        visible_snapshot = visible_snapshot[
            visible_snapshot["_quarter"].between(selected_quarters[0], selected_quarters[1])
        ].drop(columns="_quarter")
    overall_rotation = _build_overall_rotation(visible_snapshot, weighting=weighting)
    st.plotly_chart(build_overall_sector_rotation_chart(overall_rotation, weighting), width="stretch")
    st.caption(
        "Each quarter is normalized to 100% of the contributing managers' disclosed long positions. "
        "Hover over the chart to see the number of managers represented."
    )
    _render_sector_override_editor(snapshot)

    st.header("Point-in-time strategy backtests")
    st.caption(
        "Signals use the SEC acceptance timestamp - not quarter-end - and execute at the close of the "
        "next available trading session. Results shown here are long-only disclosed-book simulations."
    )

    strategy_sections = {
        "DUQ": ("Stanley Druckenmiller", "Duquesne Family Office"),
        "AM": ("David Tepper", "Appaloosa"),
        "THIEL": ("Peter Thiel", "Thiel Macro"),
    }
    tabs = st.tabs([f"{investor} - {fund}" for investor, fund in strategy_sections.values()])
    for tab, (code, (investor, fund_name)) in zip(tabs, strategy_sections.items()):
        with tab:
            _render_backtest_section(code, investor, fund_name)

    with st.expander("Backtest and data limitations", expanded=True):
        st.markdown(
            """
- Form 13F is delayed by up to 45 days and does not reveal trade dates, cash, shorts, most derivatives, or the complete macro book.
- A filing-date strategy can avoid look-ahead, but it cannot reconstruct trades made between quarter-end and publication.
- Historical ticker/CUSIP changes, confidential-treatment amendments, delistings, and missing corporate-action prices can reduce coverage.
- Yahoo adjusted closes are a convenient research input, not an institutional survivorship-free security master or total-return database.
- The "sector-balanced" comparator is long-only and equal-capital by represented sector; it is not beta-neutral or dollar-neutral.
- Thiel Macro filings are sparse and sometimes contain no public positions, so its sample can be too small for reliable inference.
            """
        )

    st.subheader("Point-in-time consensus")
    st.dataframe(payload["consensus"], width="stretch")
    st.subheader("Quarterly holdings")
    st.dataframe(payload["quarterly_holdings"], width="stretch")


if __name__ == "__main__":
    main()
