import pandas as pd

import thirteenf.cli as cli


def test_main_runs_sec_ingestion_with_explicit_arguments(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "write_fund_config", lambda: "ignored")
    monkeypatch.setattr(
        cli,
        "run_sec_ingestion",
        lambda **kwargs: pd.DataFrame([{"cusip": "037833100"}]),
    )
    cli.main(["--source", "sec", "--sec-user-agent", "Example research@example.com", "--output", str(tmp_path / "out.csv")])
    assert "Ingested 1 holdings rows from sec." in capsys.readouterr().out


def test_parser_rejects_unknown_arguments():
    parser = cli.build_parser()
    try:
        parser.parse_args(["--quaters", "8"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("unknown argument was accepted")

