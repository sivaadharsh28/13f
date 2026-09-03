from thirteenf.funds import FUND_CONFIG


EXPECTED_CIKS = {
    "PSC": "0001336528", "VFC": "0001697868", "AM": "0001656456",
    "AC": "0001112520", "BRK": "0001067983", "HC": "0001709323",
    "TCI": "0001647251", "DA": "0001671657", "DUQ": "0001536411",
    "THIEL": "0001562087",
}


def test_all_funds_use_valid_unique_sec_identity():
    assert {key: value["cik"] for key, value in FUND_CONFIG.items()} == EXPECTED_CIKS
    assert all(value["source"] == "sec" for value in FUND_CONFIG.values())
    assert all(value["aliases"] for value in FUND_CONFIG.values())

