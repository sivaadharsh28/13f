from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from thirteenf.runner import (
    rebuild_processed_snapshot,
    run_dataroma_ingestion,
    run_sec_ingestion,
    write_fund_config,
)
from thirteenf.storage import save_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="13F alpha pipeline")
    parser.add_argument("--quarter", default="current", help="Quarter label for the snapshot, e.g. 2024Q2")
    parser.add_argument("--output-dir", default="data/processed", help="Directory for processed outputs")
    parser.add_argument("--output", help="Compatibility alias for a processed output CSV")
    parser.add_argument("--source", choices=["sec", "dataroma"], default="sec", help="Live data source to ingest")
    parser.add_argument("--quarters", type=int, default=8, help="Number of report quarters to retrieve")
    parser.add_argument("--start-year", type=int, help="Retrieve SEC filings from January 1 of this year")
    parser.add_argument("--sec-user-agent", help="SEC-required user agent, e.g. 'Name email@example.com'")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    write_fund_config()
    output_dir = Path(args.output).parent if args.output else Path(args.output_dir)
    if args.source == "sec":
        if args.start_year is not None:
            current_year = date.today().year
            if args.start_year < 1999 or args.start_year > current_year:
                raise ValueError(f"--start-year must be between 1999 and {current_year}")
            snapshot = run_sec_ingestion(
                output_dir=output_dir,
                quarters=None,
                user_agent=args.sec_user_agent,
                start_date=f"{args.start_year}-01-01",
            )
        else:
            snapshot = run_sec_ingestion(
                output_dir=output_dir,
                quarters=args.quarters,
                user_agent=args.sec_user_agent,
            )
        if not snapshot.empty:
            print(f"Ingested {len(snapshot)} holdings rows from sec.")
        else:
            print("No SEC holdings were ingested.")
        return

    snapshot = run_dataroma_ingestion(output_dir=Path("data/raw"))
    if snapshot.empty:
        snapshot = rebuild_processed_snapshot(raw_dir=Path("data/raw"), output_path=Path(args.output_dir) / "combined_holdings.csv")
    output_path = Path(args.output_dir) / f"combined_holdings_{args.quarter}.csv"
    if not snapshot.empty:
        save_snapshot(snapshot, output_path)
        print(f"Saved processed snapshot to {output_path}")
    else:
        print("No Dataroma holdings were ingested.")


if __name__ == "__main__":
    main()
