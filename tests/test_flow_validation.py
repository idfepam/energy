"""Tests for per-border flow validation."""

from __future__ import annotations

import pandas as pd

from energy_collect.flow_validation import select_graph_flow_edges, validate_flows
from energy_collect.utils.zones import BorderPair


def _ts(n: int = 100) -> pd.DatetimeIndex:
    return pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")


def test_duplicate_export_detected():
    ts = _ts()
    flows = pd.DataFrame(
        {
            "timestamp": list(ts) * 2,
            "value": [100.0] * len(ts) + [100.0] * len(ts),
            "from_zone": ["FR"] * len(ts) + ["FR"] * len(ts),
            "to_zone": ["BE"] * len(ts) + ["DE_LU"] * len(ts),
        }
    )
    expected = [BorderPair("FR", "BE"), BorderPair("FR", "DE_LU")]
    results = validate_flows(flows, expected)
    statuses = {(r.from_zone, r.to_zone): r.status for r in results}
    assert statuses[("FR", "BE")] == "duplicate_export"
    assert statuses[("FR", "DE_LU")] == "duplicate_export"


def test_ok_when_distinct_series():
    ts = _ts()
    flows = pd.DataFrame(
        {
            "timestamp": list(ts) * 2,
            "value": list(range(len(ts))) + [float(x) * 2 for x in range(len(ts))],
            "from_zone": ["DE_LU"] * len(ts) + ["DE_LU"] * len(ts),
            "to_zone": ["NL"] * len(ts) + ["AT"] * len(ts),
        }
    )
    expected = [BorderPair("DE_LU", "NL"), BorderPair("DE_LU", "AT")]
    results = validate_flows(flows, expected)
    assert all(r.status == "ok" for r in results)


def test_select_graph_picks_one_per_border():
    ts = _ts()
    flows = pd.DataFrame(
        {
            "timestamp": list(ts) * 2,
            "value": [100.0] * len(ts) + [200.0] * len(ts),
            "from_zone": ["FR"] * len(ts) + ["BE"] * len(ts),
            "to_zone": ["DE_LU"] * len(ts) + ["FR"] * len(ts),
        }
    )
    expected = [BorderPair("FR", "DE_LU"), BorderPair("BE", "FR")]
    results = validate_flows(flows, expected)
    edges = select_graph_flow_edges(results, flows)
    assert len(edges) == 2
    undirected = {tuple(sorted((e["from"], e["to"]))) for e in edges}
    assert ("BE", "FR") in undirected
    assert ("DE_LU", "FR") in undirected


def test_missing_pair():
    flows = pd.DataFrame(
        columns=["timestamp", "value", "from_zone", "to_zone"],
    )
    expected = [BorderPair("FR", "BE")]
    results = validate_flows(flows, expected)
    assert results[0].status == "missing"
