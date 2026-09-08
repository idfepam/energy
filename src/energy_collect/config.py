from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass
class AppConfig:
    root: Path
    data_root: Path
    api_key: str | None
    zones: list[dict[str, Any]]
    datasets: dict[str, dict[str, Any]]
    collection: dict[str, Any]
    rate_limit: dict[str, Any]
    eu_countries: list[str]
    save_raw_xml: bool


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as f:
        return yaml.safe_load(f)


def load_config(root: Path | None = None) -> AppConfig:
    root = root or project_root()
    zones_cfg = load_yaml(root / "config" / "zones.yaml")
    datasets_cfg = load_yaml(root / "config" / "datasets.yaml")
    collection_cfg = load_yaml(root / "config" / "collection.yaml")

    data_root = root / collection_cfg["storage"]["data_root"]
    api_key = os.getenv("ENTSOE_API_KEY")

    return AppConfig(
        root=root,
        data_root=data_root,
        api_key=api_key,
        zones=zones_cfg["zones"],
        datasets=datasets_cfg["datasets"],
        collection=collection_cfg["collection"],
        rate_limit=collection_cfg["rate_limit"],
        eu_countries=zones_cfg.get("eu_countries", []),
        save_raw_xml=collection_cfg["storage"].get("save_raw_xml", False),
    )
