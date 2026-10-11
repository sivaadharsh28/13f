from __future__ import annotations

from dataclasses import replace
import os
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from thirteenf.backtest import (
    AVAILABILITY_MODELS,
    EXECUTION_PROFILES,
    PORTFOLIO_SIZE_OPTIONS,
    STRATEGY_SPECS,
    TRANSACTION_COST_BPS_OPTIONS,
    common_backtest_window,
    full_period_comparison,
    performance_summary,
    run_parameter_sweep,
    run_strategy_comparison,
)
from thirteenf.backtest_reporting import chart_assumptions, execution_steps, holding_period_explanation
from thirteenf.config import PROCESSED_DATA_DIR, SEC_USER_AGENT_ENV, SECTOR_OVERRIDE_PATH
from thirteenf.dashboard import build_dashboard_data
from thirteenf.quarterly_data import build_quarterly_sector_rotation_window
from thirteenf.monitor_ui import render_filing_change_monitor, render_sector_research_changes
from thirteenf.runner import run_sec_ingestion
from thirteenf.sector import (
    SECTOR_OPTIONS,
    apply_sector_overrides,
    build_overall_sector_rotation,
    load_sector_overrides,
    save_sector_overrides,
)
from thirteenf.ui import apply_theme, page_header
from thirteenf.storage import load_snapshot
from thirteenf.visuals import (
    build_backtest_comparison_chart,
    build_backtest_sweep_distribution_chart,
    build_backtest_sweep_scatter_chart,
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


def _shared_backtest_window() -> tuple[pd.Timestamp, pd.Timestamp]:
    histories = {}
    for code in STRATEGY_SPECS:
        path = PROCESSED_DATA_DIR / f"backtest_{code.lower()}.csv"
        status_path = PROCESSED_DATA_DIR / f"backtest_{code.lower()}_status.json"
        if not path.exists() or not status_path.exists():
            raise ValueError(f"Backtest data for {code} is needed for the common period.")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if status.get("version") != 2 or status.get("status") != "valid":
            raise ValueError(f"Backtest data for {code} must be rebuilt before comparing all funds.")
        histories[code] = _read_backtest_csv(str(path), _modified_ns(path))
    return common_backtest_window(histories)


@st.cache_data(show_spinner=False)
def _read_coverage_csv(path_text: str, modified_ns: int) -> pd.DataFrame:
    _ = modified_ns
    return pd.read_csv(path_text)


@st.cache_data(show_spinner=False)
def _performance_summary_cached(comparison: pd.DataFrame) -> pd.DataFrame:
    return performance_summary(comparison)


@st.cache_data(show_spinner=False)
def _read_events_csv(path_text: str, modified_ns: int) -> pd.DataFrame:
    _ = modified_ns
    return pd.read_csv(path_text, dtype={"cusip": str})


@st.cache_data(show_spinner=False)
def _read_price_csv(path_text: str, modified_ns: int) -> pd.DataFrame:
    _ = modified_ns
    return pd.read_csv(path_text, index_col=0, parse_dates=True)


@st.cache_data(show_spinner=False)
def _run_parameter_sweep_cached(
    code: str,
    events_path_text: str,
    events_modified_ns: int,
    prices_path_text: str,
    prices_modified_ns: int,
    open_prices_path_text: str,
    open_prices_modified_ns: int,
    benchmark_path_text: str,
    benchmark_modified_ns: int,
    top_n_values: tuple[int | None, ...],
    availability_models: tuple[str, ...],
    execution_labels: tuple[str, ...],
    transaction_cost_bps_values: tuple[int | float, ...],
    benchmark_open_modified_ns: int = 0,
    evaluation_window: tuple | None = None,
) -> pd.DataFrame:
    events = _read_events_csv(events_path_text, events_modified_ns)
    prices = _read_price_csv(prices_path_text, prices_modified_ns)
    open_prices = _read_price_csv(open_prices_path_text, open_prices_modified_ns) if open_prices_path_text else None
    benchmark_frame = _read_price_csv(benchmark_path_text, benchmark_modified_ns)
    benchmark = benchmark_frame.iloc[:, 0]
    benchmark_open_path = Path(benchmark_path_text).with_name(Path(benchmark_path_text).stem + "_open.csv")
    benchmark_opens = (_read_price_csv(str(benchmark_open_path), benchmark_open_modified_ns).iloc[:, 0]
                       if benchmark_open_path.exists() else None)
    return run_parameter_sweep(
        events,
        prices,
        benchmark,
        STRATEGY_SPECS[code],
        top_n_values=top_n_values,
        availability_models=availability_models,
        execution_labels=execution_labels,
        transaction_cost_bps_values=transaction_cost_bps_values,
        open_prices=open_prices,
        benchmark_open_prices=benchmark_opens,
        evaluation_window=evaluation_window,
    )


@st.cache_data(show_spinner=False)
def _run_scenario_comparison_cached(
    code: str,
    events_path_text: str,
    events_modified_ns: int,
    prices_path_text: str,
    prices_modified_ns: int,
    open_prices_path_text: str,
    open_prices_modified_ns: int,
    benchmark_path_text: str,
    benchmark_modified_ns: int,
    top_n: int | None,
    execution_label: str,
    transaction_cost_bps: float,
    benchmark_open_modified_ns: int = 0,
    evaluation_window: tuple | None = None,
) -> pd.DataFrame:
    events = _read_events_csv(events_path_text, events_modified_ns)
    prices = _read_price_csv(prices_path_text, prices_modified_ns)
    open_prices = _read_price_csv(open_prices_path_text, open_prices_modified_ns) if open_prices_path_text else None
    benchmark_frame = _read_price_csv(benchmark_path_text, benchmark_modified_ns)
    benchmark = benchmark_frame.iloc[:, 0]
    benchmark_open_path = Path(benchmark_path_text).with_name(Path(benchmark_path_text).stem + "_open.csv")
    benchmark_opens = (_read_price_csv(str(benchmark_open_path), benchmark_open_modified_ns).iloc[:, 0]
                       if benchmark_open_path.exists() else None)
    execution = EXECUTION_PROFILES[execution_label]
    spec = replace(
        STRATEGY_SPECS[code],
        top_n=top_n,
        availability_model="filing_date",
        execution_timing=execution["execution_timing"],
        execution_delay_sessions=execution["execution_delay_sessions"],
        transaction_cost_bps=float(transaction_cost_bps),
    )
    comparison, _ = run_strategy_comparison(events, prices, benchmark, spec, open_prices=open_prices, benchmark_open_prices=benchmark_opens)
    return full_period_comparison(comparison, *evaluation_window, calendar=benchmark.index) if evaluation_window is not None else comparison


def _configured_sec_user_agent() -> str:
    try:
        configured = str(st.secrets.get(SEC_USER_AGENT_ENV, ""))
    except Exception:
        configured = ""
    return os.getenv(SEC_USER_AGENT_ENV, configured).strip()


def _render_sec_refresh_controls(snapshot: pd.DataFrame, configured_user_agent: str) -> None:
    notice = st.session_state.pop("sec_refresh_notice", None)
    if notice:
        if notice["kind"] == "success":
            st.success(notice["message"])
        else:
            st.info(notice["message"])

    with st.expander("Refresh data from SEC EDGAR", expanded=False):
        st.caption(
            "Checks all ten tracked managers for unseen 13F accessions. Only affected report periods are "
            "downloaded and reconciled; the saved history from 2014 onward is retained."
        )
        if configured_user_agent:
            st.success("SEC request identity is configured.")
            active_user_agent = configured_user_agent
        else:
            active_user_agent = st.text_input(
                "SEC user agent",
                placeholder="Your organization your-email@example.com",
                help=(
                    "The SEC asks automated clients to identify the organization and contact email. "
                    "For a deployed app, configure THIRTEENF_SEC_USER_AGENT in Streamlit secrets."
                ),
                key="sec_refresh_user_agent",
            ).strip()
        bootstrap_quarters = st.selectbox(
            "Initial bootstrap depth",
            [2, 4, 8],
            index=0,
            format_func=lambda value: f"Latest {value} report quarters",
            help="Used only for a manager with no saved accessions. Normal refreshes fetch every unseen recent accession.",
            key="sec_refresh_bootstrap_quarters",
        )
        st.caption(
            "The request is manual and rate-limited. On hosted Streamlit services, files written by the app may "
            "be ephemeral and can disappear when the container restarts."
        )
        if st.button("Fetch latest EDGAR filings", type="primary", key="refresh_sec_edgar"):
            if not active_user_agent or "@" not in active_user_agent:
                st.error("Enter an SEC user agent containing an organization/name and contact email.")
                return
            before_accessions = set(
                snapshot.get("accession_number", pd.Series(dtype=str)).dropna().astype(str)
            )
            try:
                with st.spinner("Checking EDGAR and reconciling unseen filings..."):
                    refreshed = run_sec_ingestion(
                        user_agent=active_user_agent,
                        quarters=int(bootstrap_quarters),
                        incremental=True,
                    )
            except Exception as exc:
                st.error(f"EDGAR refresh failed; the existing snapshot was kept unchanged. {exc}")
                return

            after_accessions = set(
                refreshed.get("accession_number", pd.Series(dtype=str)).dropna().astype(str)
            )
            new_accessions = after_accessions - before_accessions
            if new_accessions:
                report_dates = pd.to_datetime(refreshed.get("report_period"), errors="coerce")
                latest_report = report_dates.max().strftime("%Y-%m-%d") if report_dates.notna().any() else "unknown"
                message = (
                    f"EDGAR refresh complete: {len(new_accessions)} new accepted filing(s) incorporated. "
                    f"Latest report period: {latest_report}."
                )
                kind = "success"
            else:
                message = "EDGAR check complete: no unseen accepted filings were found."
                kind = "info"
            st.session_state["sec_refresh_notice"] = {"kind": kind, "message": message}
            st.cache_data.clear()
            st.rerun()

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



def _render_assumption_sweep(code: str, investor: str, fund_name: str, evaluation_window: tuple) -> None:
    with st.expander("Assumption sweep: return distribution", expanded=False):
        st.caption(
            "Run a local grid across execution, portfolio breadth, and transaction-cost assumptions. "
            "All scenarios use the actual SEC acceptance timestamp. Next open uses adjusted open prices when selected."
        )
        events_path = PROCESSED_DATA_DIR / "sec_holdings_events_resolved.csv"
        prices_dir = PROCESSED_DATA_DIR.parent / "prices"
        prices_path = prices_dir / "adjusted_close.csv"
        open_prices_path = prices_dir / "adjusted_open.csv"
        benchmark_files = {
            "SPY": prices_dir / "spy.csv",
            "QQQ": prices_dir / "qqq.csv",
        }
        missing_core = [
            str(path) for path in [events_path, prices_path]
            if not path.exists()
        ]
        if missing_core:
            st.info(
                "Scenario sweeps need the saved SEC event file and local price snapshot. "
                "Run `python scripts/build_backtests.py --start 2014-01-01` after SEC ingestion."
            )
            return

        left, right = st.columns(2)
        selected_availability = ["Actual SEC filing"]
        left.caption("Disclosure availability: Actual SEC filing timestamp")
        benchmark_symbol = left.selectbox(
            "Benchmark",
            list(benchmark_files),
            key=f"benchmark_sweep_{code}",
        )
        benchmark_path = benchmark_files[benchmark_symbol]
        if not benchmark_path.exists():
            st.info(
                f"{benchmark_symbol} benchmark prices are not available yet. "
                "Run `python scripts/build_backtests.py --start 2014-01-01` to rebuild prices with SPY and QQQ."
            )
            return
        selected_execution = left.multiselect(
            "Execution assumption",
            list(EXECUTION_PROFILES),
            default=["Next close", "5-day delay"],
            key=f"execution_sweep_{code}",
        )
        selected_portfolios = right.multiselect(
            "Portfolio breadth",
            list(PORTFOLIO_SIZE_OPTIONS),
            default=["Top 10", "Full disclosed book"],
            key=f"portfolio_sweep_{code}",
        )
        selected_costs = right.multiselect(
            "Transaction cost bps",
            list(TRANSACTION_COST_BPS_OPTIONS),
            default=[10, 100],
            key=f"cost_sweep_{code}",
        )
        scenario_count = (
            len(selected_availability)
            * len(selected_execution)
            * len(selected_portfolios)
            * len(selected_costs)
        )
        st.caption(f"Selected grid: {scenario_count} scenarios. Larger grids may take longer on first run.")
        min_coverage_percent = st.slider(
            "Minimum historical event coverage (%)",
            min_value=0,
            max_value=100,
            value=0,
            step=5,
            help="Filters scenario results. Trading always requires 90% original selected-value coverage; rejected events hold cash.",
            key=f"coverage_sweep_{code}",
        )
        if st.button("Run scenario sweep", key=f"run_sweep_{code}"):
            st.session_state[f"show_sweep_{code}"] = True
        if not st.session_state.get(f"show_sweep_{code}", False):
            st.caption("Choose the assumptions to test, then run the sweep.")
            return
        if not selected_execution or not selected_portfolios or not selected_costs:
            st.warning("Select at least one option in each assumption group.")
            return

        top_n_values = tuple(PORTFOLIO_SIZE_OPTIONS[label] for label in selected_portfolios)
        availability_models = tuple(AVAILABILITY_MODELS[label] for label in selected_availability)
        transaction_costs = tuple(float(cost) for cost in selected_costs)
        with st.spinner(f"Running {fund_name} scenario grid..."):
            sweep = _run_parameter_sweep_cached(
                code,
                str(events_path),
                _modified_ns(events_path),
                str(prices_path),
                _modified_ns(prices_path),
                str(open_prices_path) if open_prices_path.exists() else "",
                _modified_ns(open_prices_path),
                str(benchmark_path),
                _modified_ns(benchmark_path),
                top_n_values,
                availability_models,
                tuple(selected_execution),
                transaction_costs,
                _modified_ns(benchmark_path.with_name(benchmark_path.stem + "_open.csv")),
                evaluation_window,
            )
        if sweep.empty:
            st.warning("No executable scenarios were produced for this assumption grid.")
            return

        invalid = sweep[sweep["status"].eq("invalid")]
        if not invalid.empty:
            st.warning(f"{len(invalid)} scenarios failed data-quality checks and are excluded.")
            st.dataframe(invalid[["portfolio_size", "execution", "error"]], hide_index=True)
        filtered = sweep[sweep["status"].eq("valid") & sweep["minimum_coverage"].ge(min_coverage_percent / 100)].copy()
        if filtered.empty:
            st.warning("No valid scenarios meet the selected coverage filter.")
            return
        cagr = filtered["cagr"].dropna()
        stats = st.columns(4)
        stats[0].metric("Scenarios", len(filtered))
        stats[1].metric("Median CAGR", f"{cagr.median():.1%}" if not cagr.empty else "n/a")
        stats[2].metric("10th percentile", f"{cagr.quantile(0.10):.1%}" if not cagr.empty else "n/a")
        stats[3].metric("90th percentile", f"{cagr.quantile(0.90):.1%}" if not cagr.empty else "n/a")

        st.plotly_chart(
            build_backtest_sweep_distribution_chart(filtered, f"{fund_name}: CAGR distribution by assumptions"),
            width="stretch",
        )
        st.plotly_chart(
            build_backtest_sweep_scatter_chart(filtered, f"{fund_name}: return versus drawdown"),
            width="stretch",
        )

        ranked = filtered.copy()
        ranked = ranked.sort_values(["portfolio_size", "execution", "transaction_cost_bps"])
        columns = [
            "portfolio_size", "availability", "execution", "transaction_cost_bps",
            "cagr", "total_return", "max_drawdown", "annualized_volatility",
            "excess_cagr", "sector_balanced_cagr", "mean_coverage", "minimum_coverage",
            "start_date", "end_date",
        ]
        st.caption("Historical sensitivity scenarios, ordered by assumptions. These results are not return forecasts.")
        st.dataframe(
            ranked[columns].style.format({
                "transaction_cost_bps": "{:.0f}",
                "cagr": "{:.1%}",
                "total_return": "{:.1%}",
                "max_drawdown": "{:.1%}",
                "annualized_volatility": "{:.1%}",
                "excess_cagr": "{:.1%}",
                "sector_balanced_cagr": "{:.1%}",
                "mean_coverage": "{:.1%}",
                "minimum_coverage": "{:.1%}",
            }),
            width="stretch",
            hide_index=True,
        )

        chart_rows = filtered.reset_index(drop=True).copy()
        chart_rows["scenario"] = chart_rows.apply(
            lambda row: (
                f"{row['portfolio_size']} | {row['execution']} | "
                f"{row['transaction_cost_bps']:.0f} bps | CAGR {row['cagr']:.1%} | DD {row['max_drawdown']:.1%}"
            ),
            axis=1,
        )
        selected_scenario = st.selectbox(
            "Scenario return path",
            chart_rows["scenario"].tolist(),
            key=f"scenario_path_{code}",
        )
        scenario = chart_rows.loc[chart_rows["scenario"].eq(selected_scenario)].iloc[0]
        scenario_top_n = None if scenario["top_n"] == "full" else int(scenario["top_n"])
        comparison = _run_scenario_comparison_cached(
            code,
            str(events_path),
            _modified_ns(events_path),
            str(prices_path),
            _modified_ns(prices_path),
                str(open_prices_path) if open_prices_path.exists() else "",
                _modified_ns(open_prices_path),
            str(benchmark_path),
            _modified_ns(benchmark_path),
            scenario_top_n,
            str(scenario["execution"]),
            float(scenario["transaction_cost_bps"]),
            _modified_ns(benchmark_path.with_name(benchmark_path.stem + "_open.csv")),
            evaluation_window,
        )
        scenario_spec = replace(
            STRATEGY_SPECS[code], top_n=scenario_top_n, benchmark=benchmark_symbol,
            transaction_cost_bps=float(scenario["transaction_cost_bps"]),
            **EXECUTION_PROFILES[str(scenario["execution"])],
        )
        st.plotly_chart(
            build_backtest_comparison_chart(
                comparison,
                f"{fund_name}: selected scenario versus {benchmark_symbol}",
                benchmark_label=benchmark_symbol,
                assumptions=chart_assumptions(scenario_spec),
            ),
            width="stretch",
        )
        _render_execution_and_metrics(comparison, scenario_spec)

        st.download_button(
            "Download sweep CSV",
            filtered.to_csv(index=False).encode("utf-8"),
            file_name=f"{code.lower()}_assumption_sweep.csv",
            mime="text/csv",
            key=f"download_sweep_{code}",
        )
def _render_execution_and_metrics(comparison, spec) -> None:
    st.markdown("##### Execution guide and assumptions")
    dates = pd.to_datetime(comparison["date"])
    st.caption(f"{dates.min():%d %b %Y} – {dates.max():%d %b %Y} · {len(comparison):,} sessions · Returns include modeled strategy trading costs.")
    with st.expander("How to follow these rules", expanded=True):
        for step in execution_steps(spec):
            st.markdown(step)
    metrics = _performance_summary_cached(comparison)
    strategy = metrics.set_index("portfolio").loc["Disclosed top positions"]
    columns = st.columns(4)
    for column, (key, label) in zip(columns, [("cagr", "Annualized return"), ("max_drawdown", "Maximum drawdown"), ("annualized_volatility", "Annualized volatility"), ("sharpe_ratio", "Sharpe ratio")]):
        value = strategy[key]
        column.metric(label, "—" if pd.isna(value) else (f"{value:.2f}" if key == "sharpe_ratio" else f"{value:.1%}"))
    _render_metrics_table(metrics)
    with st.expander("How to read the statistics"):
        st.markdown(
            "- **Maximum drawdown:** largest loss from a previous portfolio peak, including initial trading costs.\n"
            "- **Volatility:** daily return standard deviation × √252.\n"
            "- **Sharpe:** mean daily return × 252 / annualized volatility, assuming a 0% risk-free rate.\n"
            "- **Sortino:** annualized mean return / downside deviation; downside uses all sessions and a 0% target.\n"
            "- **Calmar:** compound annual growth rate (CAGR) / absolute maximum drawdown.\n"
            "- **Tracking error / information ratio:** annualized volatility of daily strategy-minus-benchmark returns, and annualized mean excess return divided by that volatility.\n"
            "- **Average exposure:** mean end-of-session invested weight; the remainder is cash.\n"
            "- **Annual gross turnover:** buys plus sells, annualized using 252 sessions. 200% means trading twice the portfolio value per year.\n"
            "- CAGR uses calendar time; other annualized statistics use 252 trading sessions and population standard deviation. Undefined ratios appear as —.\n"
            "Short samples, cash-heavy periods, data gaps and sensitivity to assumptions affect interpretation. These statistics describe the observed simulation; they do not establish future reliability."
        )


def _render_metrics_table(metrics) -> None:
    labels = {
        "portfolio": "Portfolio", "total_return": "Total return", "cagr": "CAGR",
        "annualized_volatility": "Volatility", "max_drawdown": "Max drawdown",
        "sharpe_ratio": "Sharpe (0% risk-free)", "sortino_ratio": "Sortino (0% target)",
        "calmar_ratio": "Calmar", "tracking_error": "Tracking error",
        "information_ratio": "Information ratio", "worst_daily_return": "Worst session",
        "average_exposure": "Average exposure", "annualized_turnover": "Annual gross turnover",
        "sessions": "Sessions", "window": "Evaluation window", "start_date": "Start", "end_date": "End",
    }
    percentages = ["total_return", "cagr", "annualized_volatility", "max_drawdown", "tracking_error", "worst_daily_return", "average_exposure", "annualized_turnover"]
    formats = {labels[key]: "{:.1%}" for key in percentages}
    formats.update({labels[key]: "{:.2f}" for key in ["sharpe_ratio", "sortino_ratio", "calmar_ratio", "information_ratio"]})
    formats["Sessions"] = "{:,.0f}"
    st.dataframe(metrics.rename(columns=labels).style.format(formats, na_rep="—"), width="stretch", hide_index=True)


def _render_backtest_section(code: str, investor: str, fund_name: str) -> None:
    spec = STRATEGY_SPECS[code]
    st.markdown(f"#### {investor}-inspired historical simulation")
    st.caption("Fixed rules applied to delayed disclosures. Results are historical simulations, not fund performance or projected returns.")
    rules = pd.DataFrame({
        "Rule": [
            "Signal", "Availability", "Execution", "Rebalance",
            "Maximum holding period", "Transaction costs", "Benchmark", "Sector baseline", "Coverage policy",
        ],
        "Definition": [
            f"Top {spec.top_n} reported common-equity positions, value weighted",
            "SEC acceptance timestamp; amendments to older report periods do not replace newer portfolios",
            "Configurable in the assumption sweep; headline uses next close after acceptance",
            "At each new filing event; otherwise weights drift with market returns",
            holding_period_explanation(spec),
            f"{spec.transaction_cost_bps:.0f} bps per unit of gross turnover (buys plus sells)",
            f"{spec.benchmark} buy-and-hold from the same first execution timestamp",
            "Equal capital per represented sector before filtering; unavailable allocations remain in cash",
            "At least 90% original selected-value coverage; rejected events hold cash. Missing held prices invalidate the simulation.",
        ],
    })
    st.dataframe(rules, width="stretch", hide_index=True)

    status_path = PROCESSED_DATA_DIR / f"backtest_{code.lower()}_status.json"
    if not status_path.exists():
        st.warning("The repaired historical simulation has not been built yet.")
        return
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if status.get("version") != 2 or status.get("status") != "valid":
        st.error(f"Simulation unavailable: {status.get('error', 'rebuild required')}")
        return
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

    try:
        start, end = _shared_backtest_window()
    except ValueError as exc:
        st.warning(str(exc))
        return
    comparison = full_period_comparison(comparison, start, end)
    st.caption(f"Full backtest · {start:%d %b %Y} – {end:%d %b %Y}. Same continuous period for all three strategy funds, starting at their earliest shared data availability. Existing positions carry into this period; growth is rebased to its starting capital.")

    st.plotly_chart(
        build_backtest_comparison_chart(comparison, f"{fund_name}: strategy comparison", benchmark_label=spec.benchmark, assumptions=chart_assumptions(spec)),
        width="stretch",
    )
    _render_execution_and_metrics(comparison, spec)
    if coverage_path.exists():
        try:
            coverage = _read_coverage_csv(str(coverage_path), _modified_ns(coverage_path))
        except Exception as exc:
            st.warning(f"Coverage diagnostics are not readable yet: {exc}")
            return
        execution_dates = pd.to_datetime(coverage["execution_date"], errors="coerce")
        coverage = coverage.loc[execution_dates.between(start, end)]
        active = coverage[coverage["status"].isin(["accepted", "rejected_low_coverage"])]
        columns = st.columns(3)
        columns[0].metric("Full-universe mapping", f"{active['universe_mapping_coverage'].mean():.1%}")
        columns[1].metric("Selected-value mapping", f"{active['mapping_coverage'].mean():.1%}")
        columns[2].metric("Selected-value executable", f"{active['executable_value_coverage'].mean():.1%}")
        rejected = int(coverage["status"].eq("rejected_low_coverage").sum())
        ignored = int(coverage["status"].eq("stale_report_ignored").sum())
        st.caption(f"{rejected} events target cash for insufficient coverage; {ignored} older-report amendments ignored. Coverage figures are averages across nonempty current-report events.")
        with st.expander("Per-filing coverage and unresolved securities"):
            st.dataframe(coverage, width="stretch", hide_index=True)
    _render_assumption_sweep(code, investor, fund_name, (start, end))

def _render_sector_research(snapshot: pd.DataFrame) -> None:
    render_sector_research_changes(snapshot)
    st.divider()
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


def _render_overview(snapshot: pd.DataFrame) -> None:
    st.markdown(
        '<div class="research-hero"><h2>13f Position Tracker</h2></div>',
        unsafe_allow_html=True,
    )
    values = pd.to_numeric(snapshot["market_value_usd"], errors="coerce").fillna(0)
    unknown = snapshot.get("sector", pd.Series("Unknown", index=snapshot.index)).eq("Unknown")
    unmapped = values[unknown].sum() / values.sum() if values.sum() else 0
    dates = pd.to_datetime(snapshot["report_period"], errors="coerce")
    columns = st.columns(4)
    columns[0].metric("Tracked managers", snapshot["manager_code"].nunique())
    columns[1].metric("First report", dates.min().strftime("%d %b %Y"))
    columns[2].metric("Latest report", dates.max().strftime("%d %b %Y"))
    columns[3].metric("Unmapped value · all history", f"{unmapped:.2%}")
    st.subheader("Latest manager disclosures")
    latest = snapshot.copy()
    latest["report_period"] = dates
    latest = latest[latest["report_period"].eq(latest.groupby("manager_code")["report_period"].transform("max"))]
    latest["market_value_usd"] = pd.to_numeric(latest["market_value_usd"], errors="coerce").fillna(0)
    summary = latest.groupby("fund", as_index=False).agg(
        report_period=("report_period", "max"), positions=("cusip", "nunique"),
        disclosed_value=("market_value_usd", "sum"),
    ).sort_values("disclosed_value", ascending=False)
    st.dataframe(summary, width="stretch", hide_index=True, column_config={
        "fund": st.column_config.TextColumn("Manager"),
        "report_period": st.column_config.DateColumn("Latest report", format="DD MMM YYYY"),
        "positions": st.column_config.NumberColumn("Disclosed securities", format="%d"),
        "disclosed_value": st.column_config.NumberColumn("Disclosed value", format="$%,.0f"),
    })
    st.caption("Each manager is shown at their own latest report period; reporting dates may differ.")
    st.info("Use the sidebar to explore allocations, filing changes and strategy results.")


def _render_holdings(snapshot: pd.DataFrame) -> None:
    dated_snapshot = snapshot.copy()
    dated_snapshot["quarter"] = pd.to_datetime(
        dated_snapshot["report_period"], errors="coerce"
    ).dt.to_period("Q").astype("string")
    data = _build_dashboard_payload(dated_snapshot)["quarterly_holdings"]
    left, right = st.columns(2)
    quarters = sorted(data["quarter"].dropna().unique())
    quarter = left.selectbox("Report quarter", quarters, index=len(quarters) - 1 if quarters else None)
    managers = right.multiselect("Managers", sorted(data["fund"].dropna().unique()), placeholder="All managers")
    search = st.text_input("Find a ticker", placeholder="Search symbols, e.g. AAPL")
    visible = data[data["quarter"].eq(quarter)]
    if managers:
        visible = visible[visible["fund"].isin(managers)]
    if search.strip():
        visible = visible[visible["ticker_clean"].str.contains(search.strip(), case=False, regex=False, na=False)]
    st.caption(f"{len(visible):,} holdings in this view")
    st.dataframe(visible, width="stretch", hide_index=True, column_config={
        "ticker_clean": "Ticker", "fund": "Manager", "quarter": "Quarter",
        "portfolio_weight": st.column_config.NumberColumn("Portfolio weight", format="%.2f%%"),
    })
    st.download_button("Export holdings", visible.to_csv(index=False).encode("utf-8"),
                       "quarterly_holdings.csv", "text/csv")


def main() -> None:
    st.set_page_config(page_title="13F | Research workspace", page_icon="📊", layout="wide")
    apply_theme()
    pages = {
        "Overview": "Snapshot of the latest disclosed positions and summary of tracked managers.",
        "[All Funds] Sector research": "Compare manager allocations and sector rotation over time.",
        "[Short-Term Funds] Asset Changes": "Track material position changes in accepted quarterly filings.",
        "[Short-Term Funds] Sector changes": "See where short-term managers shifted their disclosed allocations.",
        "[Short-Term Funds] Strategy backtests": "Test disclosed-book strategies using actual SEC acceptance timestamps.",
        "[All Funds] Holdings explorer": "Filter and export the quarterly disclosed positions.",
        "Data & methodology": "Refresh SEC filings, review sector mappings and understand the research limits.",
    }
    with st.sidebar:
        st.image(str(Path(__file__).resolve().parents[1] / "NUSSIF_logo.jpg"), width=200)
        st.markdown("## ◈ 13F Research")
        st.caption("INSTITUTIONAL HOLDINGS")
        st.divider()
        page = st.radio("Workspace", list(pages), key="workspace_page", label_visibility="collapsed")
        st.divider()
        st.caption("SOURCE · SEC EDGAR")
        st.caption("Delayed disclosures. Long positions only. Reported holdings may have changed since filing.")
    page_header(page, pages[page])
    try:
        snapshot = _load_snapshot()
    except Exception as exc:
        st.error(f"Saved data rejected: {exc}")
        snapshot = pd.DataFrame()
    if snapshot.empty:
        st.warning("No saved SEC holdings are available. Fetch filings to begin exploring the workspace.")
        _render_sec_refresh_controls(snapshot, _configured_sec_user_agent())
        return
    if page == "Overview":
        _render_overview(snapshot)
    elif page == "[All Funds] Sector research":
        _render_sector_research(snapshot)
    elif page in {"[Short-Term Funds] Asset Changes", "[Short-Term Funds] Sector changes"}:
        section = "Asset Changes" if page == "[Short-Term Funds] Asset Changes" else "Sector changes"
        render_filing_change_monitor(snapshot, section=section)
    elif page == "[Short-Term Funds] Strategy backtests":
        strategies = {
            "Duquesne Family Office": ("DUQ", "Stanley Druckenmiller"),
            "Appaloosa": ("AM", "David Tepper"),
            "Thiel Macro": ("THIEL", "Peter Thiel"),
        }
        fund = st.selectbox("Strategy manager", list(strategies), key="strategy_manager")
        code, investor = strategies[fund]
        _render_backtest_section(code, investor, fund)
        st.caption("Review Data & methodology for coverage assumptions and research limitations.")
    elif page == "[All Funds] Holdings explorer":
        _render_holdings(snapshot)
    else:
        st.subheader("Data management")
        _render_sec_refresh_controls(snapshot, _configured_sec_user_agent())
        _render_sector_override_editor(snapshot)
        _render_methodology()


def _render_methodology() -> None:
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


if __name__ == "__main__":
    main()
