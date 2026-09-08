from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

from energy_collect.config import AppConfig

logger = logging.getLogger(__name__)

# PyPSA-Eur OSM grid on Zenodo (latest as of Feb 2026)
ZENODO_RECORD = "18619025"
ZENODO_API = f"https://zenodo.org/api/records/{ZENODO_RECORD}"


class OSMGridCollector:
    """Download European transmission grid from PyPSA-Eur OSM dataset on Zenodo."""

    FILES = ("buses.csv", "lines.csv", "links.csv")

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.out_dir = config.data_root / "raw" / "static" / "osm_grid"

    def _get_download_urls(self) -> dict[str, str]:
        resp = httpx.get(ZENODO_API, timeout=60)
        resp.raise_for_status()
        record = resp.json()
        urls: dict[str, str] = {}
        for file_info in record.get("files", []):
            key = file_info.get("key", "")
            for target in self.FILES:
                if key.endswith(target):
                    urls[target] = file_info["links"]["self"]
        missing = set(self.FILES) - set(urls)
        if missing:
            raise RuntimeError(f"Missing files in Zenodo record: {missing}")
        return urls

    def collect(self) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        urls = self._get_download_urls()
        saved: dict[str, str] = {}

        for filename, url in urls.items():
            logger.info("Downloading %s", filename)
            resp = httpx.get(url, follow_redirects=True, timeout=300)
            resp.raise_for_status()
            csv_path = self.out_dir / f"{filename.replace('.csv', '')}_{timestamp}.csv"
            csv_path.write_bytes(resp.content)
            saved[filename] = str(csv_path)

            # Geometry columns contain commas; keep CSV as canonical, skip parquet for grid files
            logger.info("Saved %s (%s bytes)", filename, csv_path.stat().st_size)

        processed_dir = self.config.data_root / "processed" / "static"
        processed_dir.mkdir(parents=True, exist_ok=True)

        meta: dict = {
            "source": "PyPSA-Eur OSM grid (Zenodo)",
            "zenodo_record": ZENODO_RECORD,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "files": saved,
        }

        lines_csv = self.out_dir / f"lines_{timestamp}.csv"
        if lines_csv.exists():
            import shutil

            edges_path = processed_dir / "grid_lines.csv"
            shutil.copy2(lines_csv, edges_path)
            meta["processed_edges"] = str(edges_path)

        meta_path = self.out_dir / f"manifest_{timestamp}.json"
        meta_path.write_text(json.dumps(meta, indent=2))
        logger.info("Saved OSM grid files to %s", self.out_dir)
        return self.out_dir
