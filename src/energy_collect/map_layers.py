"""Build interactive map edge layers for the dashboard."""

from __future__ import annotations

from typing import Any, Callable

from energy_collect.utils.zones import border_pairs


def _node_index(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {n["id"]: n for n in nodes if "lat" in n and "lon" in n}


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi <= lo:
        return [1.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def _edge_line(
    edge: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    *,
    kind: str,
    strength_key: str = "weight",
    rank_abs: bool = False,
) -> dict[str, Any] | None:
    a, b = edge["from"], edge["to"]
    na, nb = nodes.get(a), nodes.get(b)
    if not na or not nb:
        return None
    strength = float(edge.get(strength_key, edge.get("weight", edge.get("te", 0))))
    rank_strength = abs(strength) if rank_abs else strength
    line: dict[str, Any] = {
        "from": a,
        "to": b,
        "kind": kind,
        "strength": round(strength, 5),
        "directed": bool(edge.get("directed", kind != "price")),
        "lat1": na["lat"],
        "lon1": na["lon"],
        "lat2": nb["lat"],
        "lon2": nb["lon"],
        "_rank_strength": rank_strength,
    }
    if "passes_threshold" in edge:
        line["passes_threshold"] = bool(edge["passes_threshold"])
    return line


def _normalize_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not lines:
        return []
    rank_vals = [ln["_rank_strength"] for ln in lines]
    norms = _normalize(rank_vals)
    out: list[dict[str, Any]] = []
    for ln, norm in zip(lines, norms):
        row = {k: v for k, v in ln.items() if k != "_rank_strength"}
        row["norm"] = round(norm, 4)
        out.append(row)
    return sorted(out, key=lambda x: -x["norm"])


def _pack_layer(
    lines: list[dict[str, Any]],
    *,
    strongest_filter: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    strongest_raw = [ln for ln in lines if strongest_filter(ln)]
    return {
        "all": _normalize_lines(lines),
        "strongest": _normalize_lines(strongest_raw),
        "count": len(lines),
        "count_threshold": len(strongest_raw),
    }


def _complete_border_te_edges(
    te_edges: list[dict[str, Any]],
    zones_config: list[dict],
    *,
    te_min: float,
) -> list[dict[str, Any]]:
    """One directed edge per config border pair; TE=0 when not estimated."""
    by_key = {(e["from"], e["to"]): float(e.get("te", e.get("strength", 0))) for e in te_edges}
    completed: list[dict[str, Any]] = []
    for pair in border_pairs(zones_config):
        te_val = by_key.get((pair.from_zone, pair.to_zone), 0.0)
        completed.append(
            {
                "from": pair.from_zone,
                "to": pair.to_zone,
                "te": round(te_val, 5),
                "directed": True,
                "passes_threshold": te_val >= te_min,
            }
        )
    return completed


def build_map_layers(
    graph: dict[str, Any] | None,
    te_edges: list[dict[str, Any]] | None,
    *,
    price_edges_all: list[dict[str, Any]] | None = None,
    zones_config: list[dict] | None = None,
    price_min_r: float = 0.85,
    price_strongest_floor: float = 0.80,
    te_min: float = 0.003,
) -> dict[str, Any]:
    """Return zone nodes and edge layers with all vs strongest toggles."""
    if not graph:
        return {"nodes": [], "layers": {}, "thresholds": {}}

    nodes = graph.get("nodes", [])
    node_map = _node_index(nodes)
    zone_nodes = [
        {
            "id": n["id"],
            "country": n.get("country", n["id"]),
            "lat": n["lat"],
            "lon": n["lon"],
            "substations": n.get("substation_count", 0),
        }
        for n in nodes
        if "lat" in n
    ]

    layers: dict[str, dict[str, Any]] = {}

    flow_lines = [
        x
        for e in graph.get("edges", {}).get("physical_flow", [])
        if (x := _edge_line({**e, "passes_threshold": True}, node_map, kind="flow"))
    ]
    layers["flow"] = _pack_layer(flow_lines, strongest_filter=lambda _: True)

    price_source = price_edges_all
    if not price_source:
        price_source = [
            {**e, "passes_threshold": True}
            for e in graph.get("edges", {}).get("price_coupling", [])
        ]
    price_lines = [
        x
        for e in price_source
        if (x := _edge_line(e, node_map, kind="price", rank_abs=True))
    ]
    layers["price"] = _pack_layer(
        price_lines,
        strongest_filter=lambda e: abs(e["strength"]) >= price_strongest_floor,
    )

    te_source = te_edges or []
    if zones_config:
        te_source = _complete_border_te_edges(te_source, zones_config, te_min=te_min)
    te_lines = [
        x
        for e in te_source
        if (
            x := _edge_line(
                e,
                node_map,
                kind="te",
                strength_key="te",
            )
        )
    ]
    layers["te"] = _pack_layer(
        te_lines,
        strongest_filter=lambda e: e.get("passes_threshold", e["strength"] >= te_min),
    )

    return {
        "nodes": zone_nodes,
        "layers": layers,
        "thresholds": {
            "price_min_r": price_min_r,
            "price_strongest_floor": price_strongest_floor,
            "te_min": te_min,
        },
    }
