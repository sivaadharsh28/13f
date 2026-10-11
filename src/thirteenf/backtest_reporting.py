"""Descriptions derived from the assumptions actually used by a simulation."""
from thirteenf.backtest import StrategySpec


def holding_period_explanation(spec: StrategySpec) -> str:
    return (
        f"{spec.max_holding_sessions} trading sessions, then exit to cash if no newer eligible filing. "
        "The default 63 = 252 assumed trading sessions per year / 4: roughly one quarter, "
        "matching the cadence of quarterly disclosures and limiting stale signals. "
        "It is a modeling choice, not the fund's observed holding period or a proven optimal exit. "
        "A new eligible filing resets the holding clock."
        + (" Exit at the close of session 63 counting the entry session as session 1."
           if spec.execution_timing == "next_open" and spec.max_holding_sessions == 63
           else f" Exit at the close {spec.max_holding_sessions} trading sessions after entry."
           if spec.execution_timing == "next_close"
           else f" Exit at the close of session {spec.max_holding_sessions}, counting entry as session 1.")
    )


def execution_description(spec: StrategySpec) -> str:
    price = "open" if spec.execution_timing == "next_open" else "close"
    return (
        f"Trade at the {price} of the first trading session strictly after the SEC acceptance "
        f"date in UTC, plus {spec.execution_delay_sessions} additional trading sessions."
    )


def chart_assumptions(spec: StrategySpec) -> str:
    breadth = f"Top {spec.top_n}" if spec.top_n is not None else "Full disclosed book"
    price = "Next open" if spec.execution_timing == "next_open" else "Next close"
    return (
        f"Historical simulation · {breadth} · {price} + {spec.execution_delay_sessions} sessions · "
        f"Hold ≤ {spec.max_holding_sessions} sessions<br>"
        f"Cost: {spec.transaction_cost_bps:g} bps × gross turnover · Coverage ≥ {spec.minimum_coverage:.0%} · "
        f"Cash earns 0% · Benchmark: {spec.benchmark}"
    )


def execution_steps(spec: StrategySpec) -> list[str]:
    breadth = f"Top {spec.top_n}" if spec.top_n is not None else "All"
    price = "open" if spec.execution_timing == "next_open" else "close"
    exit_timing = (
        f"Close of session {spec.max_holding_sessions}; entry day = session 1"
        if spec.execution_timing == "next_open"
        else f"Close, {spec.max_holding_sessions} trading sessions after entry"
    )
    return [
        "**1. Select & size**\n\n"
        f"- **Holdings:** {breadth} positions by reported value\n"
        "- **Ranking:** Chose Top 10 positions by reported value\n"
        "- **Signal:** Eligible SEC disclosure; ignore amendments to older report periods\n\n"
        "- **Weight**: Value of the selected position relative to the total value of Top 10 positions\n"
             r"$$w_i = \frac{V_i}{\sum_{j \in S} V_j}$$"
        "\n\n$V_i$: reported position value · $S$: original selected holdings · $w_i$: target weight",
        "**2. Enter**\n\n"
        f"- **Fill:** First trading session **{price}** strictly after the SEC acceptance date (UTC)\n"
        "- **Prices:** Adjusted historical prices; adjusted opens (accounts for dividends & stock splits) for next day open entries",
        "**3. Check coverage**\n\n"
        f"- **Minimum:** {spec.minimum_coverage:.0%} of selected positions are mapped accurately to valid tickers\n"
        "- **Allocations without valid tickers found:** Keep in cash; no redistribution\n"
        "- **Below minimum % of positions without valid tickers:** Entire portfolio to cash\n"
        "- **Missing held prices:** Simulation invalid",
        "**4. Rebalance & exit**\n\n"
        "- **Rebalance:** Each eligible filing; reset holding clock\n"
        "- **Between filings:** Let weights drift\n"
        f"- **Maximum hold:** {spec.max_holding_sessions} trading sessions\n"
        f"- **Exit to cash:** {exit_timing}, unless superseded by a new eligible filing\n"
        r"- **Why 63?** $252 / 4 = 63$ sessions $\approx$ one quarter; limits stale signals"
        "**5. Allow for costs**\n\n"
        f"- **Rate:** {spec.transaction_cost_bps:g} bps ({spec.transaction_cost_bps / 100:.2f}%) per dollar bought or sold\n"
        "- **Applies to:** Entries, rebalances and exits\n\n"
        r"$$\text{Cost fraction} = \frac{\text{bps}}{10{,}000}\sum_i |w_i^{\mathrm{target}} - w_i^{\mathrm{pretrade}}|$$"
        f"\n\n- **Full switch to different holdings:** Approximately {2 * spec.transaction_cost_bps / 100:.2f}% of portfolio value",
        "**6. Assumptions**\n\n"
        "- **Cash return:** 0%\n"
        "- **Sizing:** Fractional portfolio weights\n"
        "- **Excluded:** Taxes, leverage, shorts and options\n"
        f"- **Execution friction:** Selected cost only; no separate spread, slippage or market impact\n"
    ]
