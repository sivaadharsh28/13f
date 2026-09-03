"""Parsers for SEC Form 13F cover pages and information tables."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Iterable

import pandas as pd


HOLDING_COLUMNS = [
    "issuer", "title_of_class", "cusip", "figi", "reported_value",
    "value_unit", "market_value_usd", "shares", "share_type", "put_call",
    "investment_discretion", "other_manager", "voting_sole",
    "voting_shared", "voting_none",
]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":")[-1]


def _children_by_name(element: ET.Element, name: str) -> Iterable[ET.Element]:
    return (child for child in element.iter() if _local_name(child.tag) == name)


def _text(element: ET.Element, *names: str, default: str = "") -> str:
    for name in names:
        match = next(_children_by_name(element, name), None)
        if match is not None and match.text:
            return match.text.strip()
    return default


def _direct_text(element: ET.Element, *names: str, default: str = "") -> str:
    wanted = set(names)
    for child in element:
        if _local_name(child.tag) in wanted and child.text:
            return child.text.strip()
    return default


def _integer(value: str) -> int:
    cleaned = value.replace(",", "").strip()
    return int(cleaned) if cleaned else 0


def _share_count(info: ET.Element) -> int:
    container = next(_children_by_name(info, "shrsOrPrnAmt"), None)
    if container is None:
        return 0
    return _integer(_text(container, "sshPrnamt", "value", default="0"))


def parse_13f_xml_content(xml_content: str | bytes, value_unit: str = "usd") -> pd.DataFrame:
    """Parse a namespaced 13F information table into canonical holdings.

    ``value_unit`` must be ``usd`` for filings made under the current form or
    ``usd_thousands`` for legacy filings. Both the raw and normalized values
    are retained to keep the conversion auditable.
    """
    if value_unit not in {"usd", "usd_thousands"}:
        raise ValueError("value_unit must be 'usd' or 'usd_thousands'")
    root = ET.fromstring(xml_content)
    rows: list[dict[str, object]] = []
    multiplier = 1 if value_unit == "usd" else 1_000

    for info in _children_by_name(root, "infoTable"):
        issuer = _text(info, "nameOfIssuer")
        cusip = _text(info, "cusip").upper()
        if not issuer and not cusip:
            continue
        reported_value = _integer(_direct_text(info, "value", default="0"))
        shares = _share_count(info)
        rows.append({
            "issuer": issuer,
            "title_of_class": _text(info, "titleOfClass"),
            "cusip": cusip,
            "figi": _text(info, "figi").upper(),
            "reported_value": reported_value,
            "value_unit": value_unit,
            "market_value_usd": reported_value * multiplier,
            "shares": shares,
            "share_type": _text(info, "sshPrnamtType"),
            "put_call": _text(info, "putCall"),
            "investment_discretion": _text(info, "investmentDiscretion"),
            "other_manager": _text(info, "otherManager"),
            "voting_sole": _integer(_text(info, "Sole", default="0")),
            "voting_shared": _integer(_text(info, "Shared", default="0")),
            "voting_none": _integer(_text(info, "None", default="0")),
        })
    return pd.DataFrame(rows, columns=HOLDING_COLUMNS)


def parse_13f_cover_xml(xml_content: str | bytes) -> dict[str, object]:
    """Extract report period and amendment semantics from the cover XML."""
    root = ET.fromstring(xml_content)
    is_amendment = _text(root, "isAmendment").lower() == "true"
    is_restatement = _text(root, "isRestatement").lower() == "true"
    adds_new = _text(root, "isOther").lower() == "true"
    # Current 13F XML schemas use an enum inside ``amendmentInfo`` rather
    # than the boolean fields used by older filings.  For example, Pershing
    # Square accession 0001172661-25-001497 contains
    # ``<amendmentType>NEW HOLDINGS</amendmentType>``.
    amendment_type_raw = " ".join(
        _text(root, "amendmentType").upper().replace("_", " ").replace("-", " ").split()
    )
    if amendment_type_raw == "RESTATEMENT":
        is_restatement = True
    elif amendment_type_raw in {"NEW HOLDINGS", "NEW HOLDING", "ADDS NEW HOLDINGS"}:
        adds_new = True
    return {
        "report_period": _text(root, "reportCalendarOrQuarter", "periodOfReport"),
        "is_amendment": is_amendment,
        "amendment_number": _text(root, "amendmentNo"),
        "amendment_type_raw": amendment_type_raw,
        "amendment_type": (
            "restatement" if is_restatement else "adds_new_holdings" if adds_new else ""
        ),
    }
