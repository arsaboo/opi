"""
Utilities for retrieving and caching sector allocation data per symbol, along
with helpers to aggregate portfolio exposure by sector.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import requests
from requests import Response, Session

logger = logging.getLogger(__name__)


ALL_SECTORS: Tuple[str, ...] = (
    "Materials",
    "Consumer Cyclical",
    "Financial Services",
    "Real Estate",
    "Communication Services",
    "Energy",
    "Industrials",
    "Technology",
    "Consumer Defensive",
    "Healthcare",
    "Utilities",
    "Unknown",
)

SECTOR_ALIASES = {
    "basic materials": "Materials",
    "materials": "Materials",
    "consumer cyclical": "Consumer Cyclical",
    "consumer discretionary": "Consumer Cyclical",
    "financial services": "Financial Services",
    "financials": "Financial Services",
    "financial": "Financial Services",
    "real estate": "Real Estate",
    "communication services": "Communication Services",
    "comm services": "Communication Services",
    "communications": "Communication Services",
    "communication": "Communication Services",
    "telecommunication services": "Communication Services",
    "energy": "Energy",
    "industrials": "Industrials",
    "industrial": "Industrials",
    "technology": "Technology",
    "information technology": "Technology",
    "consumer defensive": "Consumer Defensive",
    "consumer staples": "Consumer Defensive",
    "healthcare": "Healthcare",
    "health care": "Healthcare",
    "utilities": "Utilities",
    "utility": "Utilities",
}

SYMBOL_SECTOR_ALIASES = {
    "$SPX": "SPY",
    "SPX": "SPY",
    ".INX": "SPY",
}

class RateLimitError(RuntimeError):
    """Raised when an upstream API reports a rate limit condition."""


def _canonical_sector_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    key = re.sub(r"[^a-zA-Z]+", " ", name).strip().lower()
    return SECTOR_ALIASES.get(key)


MANUAL_SECTOR_DATA = {}


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    totals = {sector: 0.0 for sector in ALL_SECTORS}
    for sector, value in weights.items():
        canonical = _canonical_sector_name(sector)
        if canonical is None and sector in totals:
            canonical = sector
        if canonical is None:
            canonical = "Unknown"
        try:
            totals[canonical] += float(value)
        except (TypeError, ValueError):
            continue

    known_total = sum(totals[sector] for sector in ALL_SECTORS if sector != "Unknown")
    unknown = totals["Unknown"]
    remainder = round(100.0 - (known_total + unknown), 6)
    if remainder > 0:
        unknown += remainder
    totals["Unknown"] = unknown

    # If totals drift significantly, scale them back to approximately 100%.
    grand_total = sum(totals.values())
    if grand_total and not 95.0 <= grand_total <= 105.0:
        scale = 100.0 / grand_total
        for sector in totals:
            totals[sector] = round(totals[sector] * scale, 2)
    else:
        for sector in totals:
            totals[sector] = round(totals[sector], 2)

    return totals


def _is_unknown_only(weights: Dict[str, float]) -> bool:
    if not weights:
        return True
    unknown = weights.get("Unknown", 0.0)
    others = sum(value for sector, value in weights.items() if sector != "Unknown")
    return unknown >= 99.0 and others <= 1.0


def _is_single_sector(weights: Dict[str, float]) -> bool:
    """Return True when exactly one sector holds ~100% of the allocation."""
    if not weights:
        return False
    dominant = [sector for sector, value in weights.items() if isinstance(value, (int, float)) and value >= 99.0]
    return len(dominant) == 1


def _isoformat_from_timestamp(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class SectorEntry:
    symbol: str
    weights: Dict[str, float]
    source: str
    last_updated: str
    metadata: Dict[str, str]


class SectorCache:
    """On-disk cache of per-symbol sector allocations."""

    def __init__(
        self,
        cache_path: Optional[Path] = None,
        seed_data: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> None:
        self.cache_path = cache_path or Path(__file__).resolve().parent.parent / "sector_cache.json"
        self.cache_path = self.cache_path.resolve()
        self._data, changed = self._load()
        if seed_data:
            changed = self._merge_seed(seed_data) or changed
        if changed:
            self._save()

    def _load(self) -> Tuple[Dict[str, Dict[str, object]], bool]:
        if not self.cache_path.exists():
            return {}, False
        try:
            with self.cache_path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception as exc:
            logger.warning("Failed to load sector cache %s: %s", self.cache_path, exc)
            return {}, False

        if isinstance(raw, dict):
            upgraded, changed = self._upgrade_schema(raw)
            return upgraded, changed
        return {}, True

    def _upgrade_schema(self, raw: Dict[str, object]) -> Tuple[Dict[str, Dict[str, object]], bool]:
        upgraded: Dict[str, Dict[str, object]] = {}
        changed = False
        for key, value in raw.items():
            symbol = str(key).upper()
            if not isinstance(value, dict):
                continue
            if "weights" in value:
                weights = value.get("weights") or {}
                upgraded[symbol] = {
                    "weights": _normalize_weights(weights),
                    "source": value.get("source", "cache"),
                    "last_updated": value.get("last_updated") or _now_iso(),
                    "metadata": value.get("metadata", {}),
                }
                continue
            if "sector" in value:
                weights = {value.get("sector"): 100.0}
                upgraded[symbol] = {
                    "weights": _normalize_weights(weights),
                    "source": "legacy",
                    "last_updated": value.get("last_updated")
                    or _isoformat_from_timestamp(value.get("timestamp"))
                    or _now_iso(),
                    "metadata": {},
                }
                changed = True
                continue
            if all(isinstance(v, (int, float)) for v in value.values()):
                upgraded[symbol] = {
                    "weights": _normalize_weights(value),
                    "source": "legacy",
                    "last_updated": _now_iso(),
                    "metadata": {},
                }
                changed = True
        return upgraded, changed

    def _merge_seed(self, seed: Dict[str, Dict[str, float]]) -> bool:
        changed = False
        for symbol, weights in seed.items():
            sym = symbol.upper()
            normalized_seed = _normalize_weights(weights)
            existing = self._data.get(sym)
            # Only merge if symbol doesn't exist or is unknown-only
            # Do NOT update timestamp for existing symbols to avoid marking them as "updated"
            if existing is None:
                self._data[sym] = {
                    "weights": normalized_seed,
                    "source": "manual_seed",
                    "last_updated": _now_iso(),
                    "metadata": {},
                }
                changed = True
            elif _is_unknown_only(existing.get("weights", {})):
                # Update weights but preserve original timestamp to avoid false "updates"
                self._data[sym] = {
                    "weights": normalized_seed,
                    "source": "manual_seed",
                    "last_updated": existing.get("last_updated") or _now_iso(),
                    "metadata": existing.get("metadata", {}),
                }
                changed = True
        return changed

    def _save(self) -> None:
        tmp_path = self.cache_path.with_suffix(".tmp")
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, sort_keys=True)
        tmp_path.replace(self.cache_path)

    def get_entry(self, symbol: str) -> Optional[SectorEntry]:
        data = self._data.get(symbol.upper())
        if not data:
            return None
        return SectorEntry(
            symbol=symbol.upper(),
            weights=_normalize_weights(data.get("weights", {})),
            source=data.get("source", "unknown"),
            last_updated=data.get("last_updated", _now_iso()),
            metadata=data.get("metadata", {}),
        )

    def needs_refresh(self, symbol: str, ttl: timedelta) -> bool:
        entry = self._data.get(symbol.upper())
        if not entry:
            return True
        last_updated = entry.get("last_updated")
        if not last_updated:
            return True
        try:
            updated = datetime.fromisoformat(last_updated)
        except ValueError:
            return True
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - updated > ttl

    def update_entry(
        self,
        symbol: str,
        weights: Dict[str, float],
        source: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> SectorEntry:
        meta = metadata or {}
        existing_meta = self._data.get(symbol.upper(), {}).get("metadata", {})
        combined_meta = {**existing_meta, **meta}
        entry = {
            "weights": _normalize_weights(weights),
            "source": source,
            "last_updated": _now_iso(),
            "metadata": combined_meta,
        }
        self._data[symbol.upper()] = entry
        self._save()
        return SectorEntry(
            symbol=symbol.upper(),
            weights=entry["weights"],
            source=entry["source"],
            last_updated=entry["last_updated"],
            metadata=entry["metadata"],
        )

    def ensure_unknown(self, symbol: str) -> SectorEntry:
        entry = self._data.get(symbol.upper())
        if entry:
            return self.get_entry(symbol)  # type: ignore[return-value]
        entry = {
            "weights": _normalize_weights({"Unknown": 100.0}),
            "source": "unknown",
            "last_updated": _now_iso(),
            "metadata": {},
        }
        self._data[symbol.upper()] = entry
        self._save()
        return SectorEntry(
            symbol=symbol.upper(),
            weights=entry["weights"],
            source=entry["source"],
            last_updated=entry["last_updated"],
            metadata={},
        )


class SectorDataProvider:
    """Fetch sector exposure data from APIs with caching."""

    def __init__(
        self,
        cache: Optional[SectorCache] = None,
        *,
        ttl_days: int = 30,
        session: Optional[Session] = None,
        alphavantage_key: Optional[str] = None,
    ) -> None:
        self.cache = cache or SectorCache(seed_data=MANUAL_SECTOR_DATA)
        self.ttl = timedelta(days=ttl_days)
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        )
        self.session.headers.setdefault("Accept", "application/json, text/html")
        self.alphavantage_key = alphavantage_key or os.getenv("ALPHAVANTAGE_API_KEY")
        self.updated_symbols: set[str] = set()

    def get_sector_entry(
        self,
        symbol: str,
        *,
        force_refresh: bool = False,
    ) -> SectorEntry:
        return self._get_sector_entry_resolved(symbol.upper(), force_refresh, set())

    def _get_sector_entry_resolved(
        self,
        symbol: str,
        force_refresh: bool,
        visited: set[str],
    ) -> SectorEntry:
        if symbol in visited:  # Prevent alias cycles
            return self.cache.ensure_unknown(symbol)
        visited.add(symbol)

        alias_target = SYMBOL_SECTOR_ALIASES.get(symbol)
        if alias_target:
            base_symbol = alias_target.upper()
            base_entry = self._get_sector_entry_resolved(base_symbol, force_refresh, visited)
            metadata = dict(base_entry.metadata)
            metadata["alias_of"] = base_symbol
            previous = self.cache.get_entry(symbol)

            if _is_unknown_only(base_entry.weights) and previous:
                logger.info(
                    "Skipped sector update for %s (alias of %s) because weights are 100%% Unknown",
                    symbol,
                    base_symbol,
                )
                return previous

            updated = self.cache.update_entry(symbol, base_entry.weights, base_entry.source, metadata)
            self._record_update(symbol, previous, updated)
            return updated

        entry = self.cache.get_entry(symbol)
        needs_refresh = force_refresh or self.cache.needs_refresh(symbol, self.ttl)

        if entry and not force_refresh and _is_single_sector(entry.weights):
            return entry

        if entry and not needs_refresh:
            return entry

        refreshed = self._refresh_symbol(symbol, existing=entry)
        if refreshed:
            self._record_update(symbol, entry, refreshed)
            return refreshed

        if entry:
            return entry

        # Only record as updated if we're creating a new unknown entry
        unknown_entry = self.cache.ensure_unknown(symbol)
        if entry is None:
            self._record_update(symbol, None, unknown_entry)
        return unknown_entry

    def _record_update(
        self,
        symbol: str,
        previous: Optional[SectorEntry],
        new_entry: SectorEntry,
    ) -> None:
        # Always mark as updated if this is a new entry or if data changed
        if previous is None:
            self.updated_symbols.add(symbol)
            return
        if (
            previous.weights != new_entry.weights
            or previous.source != new_entry.source
            or previous.metadata != new_entry.metadata
        ):
            self.updated_symbols.add(symbol)

    def clear_updated_symbols(self) -> None:
        self.updated_symbols.clear()

    def _refresh_symbol(
        self,
        symbol: str,
        existing: Optional[SectorEntry] = None,
    ) -> Optional[SectorEntry]:
        try:
            result = self._fetch_from_alpha_vantage_etf(symbol)
        except RateLimitError as exc:
            logger.warning("%s", exc)
            raise
        except Exception as exc:
            logger.debug("ETF profile fetch failed for %s: %s", symbol, exc)
            result = None

        if not result:
            return None

        weights, meta = result
        normalized_weights = _normalize_weights(weights)
        if _is_unknown_only(normalized_weights) and existing:
            logger.info(
                "Skipped sector update for %s from %s because weights are 100%% Unknown",
                symbol,
                meta.get("source", "alpha_vantage_etf"),
            )
            return None
        return self.cache.update_entry(symbol, normalized_weights, meta.get("source", "alpha_vantage_etf"), meta)

    def _fetch_json(self, url: str, *, params: Optional[Dict[str, str]] = None) -> Optional[Dict]:
        response: Response = self.session.get(url, params=params, timeout=15)
        if response.status_code == 429:
            raise RateLimitError(f"Rate limit reached for {url}")
        if response.status_code >= 400:
            logger.debug("HTTP %s for %s", response.status_code, response.url)
            return None
        try:
            return response.json()
        except ValueError:
            logger.debug("Failed to decode JSON from %s", response.url)
            return None

    def _fetch_from_alpha_vantage_etf(
        self, symbol: str
    ) -> Optional[Tuple[Dict[str, float], Dict[str, str]]]:
        if not self.alphavantage_key:
            return None
        url = "https://www.alphavantage.co/query"
        params = {"function": "ETF_PROFILE", "symbol": symbol, "apikey": self.alphavantage_key}
        data = self._fetch_json(url, params=params)
        if not data:
            return None
        note = data.get("Note") if isinstance(data, dict) else None
        if note:
            logger.warning("Alpha Vantage rate limit reached: %s", note)
            raise RateLimitError("Alpha Vantage rate limit reached")
        sectors = data.get("sectors")
        if not isinstance(sectors, list):
            return None
        parsed: Dict[str, float] = {}
        for item in sectors:
            if not isinstance(item, dict):
                continue
            name = item.get("sector")
            val = _safe_float(item.get("weight"))
            if val is None:
                continue
            if name:
                parsed[str(name).title()] = val * 100 if val <= 1 else val
        if parsed:
            return parsed, {"source": "alpha_vantage_etf"}
        return None



class PortfolioSectorAnalyzer:
    """Aggregate sector exposure for a collection of account positions."""

    def __init__(self, provider: SectorDataProvider) -> None:
        self.provider = provider

    def analyze_positions(
        self,
        positions: Iterable[Dict[str, object]],
        *,
        force_refresh: bool = False,
    ) -> Dict[str, object]:
        aggregated: Dict[str, Dict[str, object]] = {}
        total_value = 0.0
        gross_value = 0.0

        for position in positions:
            symbol = position.get("baseSymbol") or position.get("symbol")
            if not symbol:
                continue
            market_value = _safe_float(position.get("marketValue"))
            if market_value is None:
                continue
            symbol = str(symbol).upper()
            entry = aggregated.setdefault(
                symbol,
                {"market_value": 0.0, "positions": []},
            )
            entry["market_value"] += market_value
            entry["positions"].append(position)
            total_value += market_value
            gross_value += abs(market_value)

        totals = {sector: 0.0 for sector in ALL_SECTORS}
        per_symbol: Dict[str, Dict[str, object]] = {}

        for symbol, info in aggregated.items():
            entry = self.provider.get_sector_entry(symbol, force_refresh=force_refresh)
            weights = entry.weights
            per_symbol[symbol] = {
                "market_value": round(info["market_value"], 2),
                "weights": {sector: weights.get(sector, 0.0) for sector in ALL_SECTORS},
                "source": entry.source,
                "last_updated": entry.last_updated,
                "metadata": entry.metadata,
            }
            for sector, percent in weights.items():
                totals[sector] += info["market_value"] * (percent / 100.0)

        percent_totals = {}
        denominator = total_value if total_value else gross_value
        if denominator:
            for sector, value in totals.items():
                percent_totals[sector] = round(value / denominator * 100.0, 4)
        else:
            for sector in totals:
                percent_totals[sector] = 0.0

        return {
            "as_of": _now_iso(),
            "total_market_value": round(total_value, 2),
            "gross_market_value": round(gross_value, 2),
            "sector_values": {k: round(v, 2) for k, v in totals.items()},
            "sector_percentages": percent_totals,
            "per_symbol": per_symbol,
        }

    def analyze_from_api(self, api, *, force_refresh: bool = False) -> Dict[str, object]:
        positions = getattr(api, "get_account_positions")()
        return self.analyze_positions(positions, force_refresh=force_refresh)
