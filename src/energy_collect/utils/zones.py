from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterator


@dataclass(frozen=True)
class BorderPair:
    from_zone: str
    to_zone: str


def zone_codes(zones: list[dict]) -> list[str]:
    return [z["code"] for z in zones]


def border_pairs(zones: list[dict]) -> list[BorderPair]:
    """Generate directed border pairs from zone adjacency lists."""
    known = {z["code"] for z in zones}
    pairs: set[tuple[str, str]] = set()
    for zone in zones:
        src = zone["code"]
        for dst in zone.get("neighbors", []):
            if dst in known:
                pairs.add((src, dst))
    return [BorderPair(a, b) for a, b in sorted(pairs)]


def month_ranges(year: int) -> list[tuple[str, str]]:
    """Return (start, end) date strings for each month in a year."""
    ranges: list[tuple[str, str]] = []
    for month in range(1, 13):
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)
        ranges.append((start.isoformat(), end.isoformat()))
    return ranges


def year_range(year: int) -> tuple[str, str]:
    return f"{year}-01-01", f"{year + 1}-01-01"
