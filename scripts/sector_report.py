#!/usr/bin/env python
"""
Utility script to generate a sector allocation report for the current portfolio.

Usage examples:
    python scripts/sector_report.py --symbols SPY QQQ VGT
    python scripts/sector_report.py --positions sample_positions.json
    python scripts/sector_report.py --from-api --force-refresh
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv()

from api import Api
from services import PortfolioSectorAnalyzer, SectorDataProvider
from services.sector_allocation_service import RateLimitError


def _build_api() -> Api:
    api_key = os.getenv("SCHWAB_API_KEY")
    redirect_uri = os.getenv("SCHWAB_REDIRECT_URI")
    app_secret = os.getenv("SCHWAB_APP_SECRET")
    account_id = os.getenv("SCHWAB_ACCOUNT_ID")
    missing = [name for name, value in (
        ("SCHWAB_API_KEY", api_key),
        ("SCHWAB_REDIRECT_URI", redirect_uri),
        ("SCHWAB_APP_SECRET", app_secret),
        ("SCHWAB_ACCOUNT_ID", account_id),
    ) if not value]
    if missing:
        raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")

    api = Api(api_key, redirect_uri, app_secret)
    api.setup()
    return api


def _load_positions_from_file(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict) and "positions" in data:
        data = data["positions"]
    if not isinstance(data, list):
        raise ValueError("Expected a list of positions or a JSON object with a 'positions' key")
    return data


def _positions_from_symbols(symbols: Iterable[str]) -> List[dict]:
    return [
        {
            "symbol": sym.upper(),
            "baseSymbol": sym.upper(),
            "assetType": "MANUAL",
            "marketValue": 1.0,
            "longQuantity": 1.0,
            "shortQuantity": 0.0,
        }
        for sym in symbols
    ]


def _format_currency(value: float) -> str:
    return f"${value:,.2f}"


def _parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_static_single_sector(weights: dict) -> bool:
    if not weights:
        return False
    dominant = [sector for sector, val in weights.items() if isinstance(val, (int, float)) and val >= 99.9]
    return len(dominant) == 1


def _collect_stale_symbols(
    provider: SectorDataProvider, *, max_age: timedelta
) -> List[Tuple[str, datetime]]:
    now = datetime.now(timezone.utc)
    stale: List[Tuple[str, datetime]] = []

    cache_data = getattr(provider.cache, "_data", {})
    for symbol, entry in cache_data.items():
        weights = entry.get("weights", {})
        if _is_static_single_sector(weights):
            continue
        last_updated = _parse_iso_timestamp(entry.get("last_updated"))
        if last_updated is None:
            continue
        if now - last_updated > max_age:
            stale.append((symbol, last_updated))

    stale.sort(key=lambda item: item[1])
    return stale


def _print_report(report: dict, updated_symbols: set[str] | None = None) -> None:
    print(f"Report generated at: {report.get('as_of')}")
    print(f"Net market value : {_format_currency(report.get('total_market_value', 0.0))}")
    print(f"Gross market value: {_format_currency(report.get('gross_market_value', 0.0))}")
    print("\nSector exposure (percent of gross market value):")
    sector_percentages = report.get("sector_percentages", {})
    sector_values = report.get("sector_values", {})
    for sector, percentage in sector_percentages.items():
        value = sector_values.get(sector, 0.0)
        print(f"  {sector:>20}: {percentage:6.2f}% ({_format_currency(value)})")

    per_symbol = report.get("per_symbol", {})
    if updated_symbols is not None:
        per_symbol = {sym: details for sym, details in per_symbol.items() if sym in updated_symbols}

    if per_symbol:
        print("\nPer-symbol breakdown (updated symbols only):")
        for symbol, details in per_symbol.items():
            print(f"  {symbol}: value={_format_currency(details.get('market_value', 0.0))} "
                  f"source={details.get('source')} updated={details.get('last_updated')}")
            weights = details.get("weights", {})
            sector_line = ", ".join(f"{sector} {weight:.2f}%" for sector, weight in weights.items() if weight)
            print(f"    sectors: {sector_line or 'Unknown'}")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a sector allocation report.")
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--from-api", action="store_true", help="Fetch positions from Schwab API.")
    source_group.add_argument(
        "--positions",
        type=Path,
        help="Path to a JSON file containing positions (list or {'positions': [...]})",
    )
    source_group.add_argument(
        "--symbols",
        nargs="+",
        help="List of tickers to include with equal weighting (for quick testing).",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore the 30 day cache window and refetch sector data.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the report as JSON.",
    )

    args = parser.parse_args(argv)

    provider = SectorDataProvider()
    analyzer = PortfolioSectorAnalyzer(provider)

    provider.clear_updated_symbols()

    # Debug: confirm updated_symbols is empty before analysis
    print(f"DEBUG: updated_symbols before analysis: {provider.updated_symbols}")

    if args.from_api:
        api = _build_api()
        try:
            report = analyzer.analyze_from_api(api, force_refresh=args.force_refresh)
        except RateLimitError as exc:
            print(f"ERROR: {exc}")
            return 1
    elif args.positions:
        positions = _load_positions_from_file(args.positions)
        report = analyzer.analyze_positions(positions, force_refresh=args.force_refresh)
    elif args.symbols:
        positions = _positions_from_symbols(args.symbols)
        report = analyzer.analyze_positions(positions, force_refresh=args.force_refresh)
    else:
        parser.error("Please specify one of --from-api, --positions, or --symbols.")

    # Debug: show updated_symbols after analysis
    print(f"DEBUG: updated_symbols after analysis: {provider.updated_symbols}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"Wrote report to {args.output}")

    if provider.updated_symbols:
        updated_list = ", ".join(sorted(provider.updated_symbols))
        print(f"\nUpdated sector data this run: {updated_list}")

    stale_symbols = _collect_stale_symbols(provider, max_age=timedelta(days=30))
    if stale_symbols:
        print("\nSector data older than 30 days (excluding static single-sector assets):")
        for symbol, dt in stale_symbols:
            print(f"  {symbol}: last updated {dt.isoformat()}")

    _print_report(report, provider.updated_symbols)
    return 0


if __name__ == "__main__":
    sys.exit(main())
