from pathlib import Path

from energy_collect.utils.zones import border_pairs, month_ranges, year_range, zone_codes


def test_zone_codes():
    zones = [{"code": "FR", "neighbors": ["DE_LU"]}, {"code": "DE_LU", "neighbors": ["FR"]}]
    assert zone_codes(zones) == ["FR", "DE_LU"]


def test_border_pairs_directed():
    zones = [{"code": "FR", "neighbors": ["DE_LU"]}, {"code": "DE_LU", "neighbors": ["FR"]}]
    pairs = border_pairs(zones)
    assert ("FR", "DE_LU") in [(p.from_zone, p.to_zone) for p in pairs]
    assert ("DE_LU", "FR") in [(p.from_zone, p.to_zone) for p in pairs]


def test_year_range():
    start, end = year_range(2025)
    assert start == "2025-01-01"
    assert end == "2026-01-01"


def test_month_ranges():
    ranges = month_ranges(2025)
    assert len(ranges) == 12
    assert ranges[0] == ("2025-01-01", "2025-02-01")
    assert ranges[11] == ("2025-12-01", "2026-01-01")


def test_manifest_job_id():
    from energy_collect.storage.manifest import Manifest

    job_id = Manifest.make_job_id("day_ahead_prices", "FR", "2025-01-01", "2026-01-01")
    assert "day_ahead_prices" in job_id
    assert "FR" in job_id
