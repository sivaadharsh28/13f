import pandas as pd

from thirteenf.scrapers.dataroma import parse_dataroma_html
from thirteenf.scrapers.sec_edgar import parse_13f_xml_content


SAMPLE_DATAROMA_HTML = """
<table id="etf">
    <tr>
        <th>Ticker</th>
        <th>Company</th>
        <th>% Port</th>
        <th>Shares</th>
        <th>Market Value</th>
    </tr>
    <tr>
        <td>BRK.B</td>
        <td>Berkshire</td>
        <td>12.5%</td>
        <td>1,000</td>
        <td>$1.2M</td>
    </tr>
    <tr>
        <td>AAPL</td>
        <td>Apple</td>
        <td>8.2%</td>
        <td>2,000</td>
        <td>$2.0M</td>
    </tr>
</table>
"""


SAMPLE_13F_XML = """
<edgarSubmission>
    <informationTable>
        <infoTable>
            <nameOfIssuer>Apple Inc</nameOfIssuer>
            <titleOfClass>COM</titleOfClass>
            <cusip>037833100</cusip>
            <shrsOrPrnAmt>
                <value>2500</value>
            </shrsOrPrnAmt>
            <value>250000</value>
        </infoTable>
        <infoTable>
            <nameOfIssuer>Microsoft Corp</nameOfIssuer>
            <titleOfClass>COM</titleOfClass>
            <cusip>594918104</cusip>
            <shrsOrPrnAmt>
                <value>4200</value>
            </shrsOrPrnAmt>
            <value>420000</value>
        </infoTable>
    </informationTable>
</edgarSubmission>
"""


def test_parse_dataroma_html_extracts_holdings():
    df = parse_dataroma_html(SAMPLE_DATAROMA_HTML, "BRK", "Berkshire")

    assert len(df) == 2
    assert list(df.columns) == [
        "ticker",
        "company",
        "pct_portfolio",
        "shares",
        "market_value_m",
        "fund",
        "fund_code",
    ]
    assert df.iloc[0]["ticker"] == "BRK.B"
    assert df.iloc[0]["pct_portfolio"] == 12.5
    assert df.iloc[0]["market_value_m"] == 1.2


def test_parse_13f_xml_content_extracts_issuers_and_shares():
    df = parse_13f_xml_content(SAMPLE_13F_XML)

    assert len(df) == 2
    assert "market_value_usd" in df.columns
    assert "cusip" in df.columns
    assert df.iloc[0]["cusip"] == "037833100"
    assert df.iloc[0]["shares"] == 2500
    assert df.iloc[0]["reported_value"] == 250000
    assert df.iloc[0]["market_value_usd"] == 250000


def test_parse_dataroma_html_rejects_malformed_symbols():
    html = """
    <table id="etf">
        <tr><th>Ticker</th><th>Company</th><th>% Port</th><th>Shares</th><th>Market Value</th></tr>
        <tr><td>≡</td><td>Bad Symbol</td><td>12.5%</td><td>1,000</td><td>$1.2M</td></tr>
        <tr><td>BRK.B</td><td>Berkshire</td><td>8.2%</td><td>2,000</td><td>$2.0M</td></tr>
    </table>
    """

    df = parse_dataroma_html(html, "BRK", "Berkshire")

    assert len(df) == 1
    assert df.iloc[0]["ticker"] == "BRK.B"
