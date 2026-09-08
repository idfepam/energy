from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import httpx
import pandas as pd

from energy_collect.config import AppConfig
from energy_collect.utils.gem_countries import gem_region_country_names

logger = logging.getLogger(__name__)

GIPT_DOWNLOAD_URL = (
    "https://globalenergymonitor.org/projects/global-integrated-power-tracker/download-data/"
)
GIPT_DATA_SHEET = "Power facilities"
COUNTRY_COLUMNS = ("Country/area", "Country/Area", "Country", "country")


class GEMCollector:
    """Import Global Energy Monitor power plant data for the coupling region."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.out_dir = config.data_root / "raw" / "static" / "gem"

    def collect(self, xlsx_url: str | None = None, xlsx_file: str | Path | None = None) -> Path:
        """Download or import GIPT XLSX and write EU/region plant parquet."""
        self.out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")

        if xlsx_file:
            return self._import_file(Path(xlsx_file), timestamp)
        if xlsx_url:
            return self._import_url(xlsx_url, timestamp)
        raise ValueError(
            "GEM import requires --file or --url. Get the latest XLSX from "
            f"{GIPT_DOWNLOAD_URL}"
        )

    def _import_file(self, src: Path, timestamp: str) -> Path:
        if not src.exists():
            raise FileNotFoundError(src)
        logger.info("Importing GEM data from %s", src)
        raw_path = self.out_dir / f"gipt_{timestamp}.xlsx"
        shutil.copy2(src, raw_path)
        return self._process_xlsx(raw_path.read_bytes(), source=str(src), timestamp=timestamp)

    def _import_url(self, xlsx_url: str, timestamp: str) -> Path:
        logger.info("Downloading GEM data from %s", xlsx_url)
        resp = httpx.get(xlsx_url, follow_redirects=True, timeout=120)
        resp.raise_for_status()
        raw_path = self.out_dir / f"gipt_{timestamp}.xlsx"
        raw_path.write_bytes(resp.content)
        return self._process_xlsx(resp.content, source=xlsx_url, timestamp=timestamp)

    def _process_xlsx(self, content: bytes, *, source: str, timestamp: str) -> Path:
        xl = pd.ExcelFile(BytesIO(content))
        sheet = GIPT_DATA_SHEET if GIPT_DATA_SHEET in xl.sheet_names else xl.sheet_names[0]
        if sheet != GIPT_DATA_SHEET:
            logger.warning("Sheet %r not found; using %r", GIPT_DATA_SHEET, sheet)

        df = pd.read_excel(BytesIO(content), sheet_name=sheet)
        country_col = next((c for c in COUNTRY_COLUMNS if c in df.columns), None)
        region_names = gem_region_country_names()

        if country_col:
            eu_df = df[df[country_col].astype(str).str.strip().isin(region_names)].copy()
        else:
            logger.warning("Could not find country column; saving full dataset")
            eu_df = df.copy()

        # Mixed int/str cells break parquet export
        for col in eu_df.select_dtypes(include=["object"]).columns:
            eu_df[col] = eu_df[col].astype(str).where(eu_df[col].notna(), None)

        out_path = self.out_dir / f"plants_eu_{timestamp}.parquet"
        eu_df.to_parquet(out_path, index=False)

        meta = {
            "source": "Global Energy Monitor - Global Integrated Power Tracker",
            "source_file": source,
            "sheet": sheet,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "rows_total": len(df),
            "rows_region": len(eu_df),
            "raw_file": str(self.out_dir / f"gipt_{timestamp}.xlsx"),
            "processed_file": str(out_path),
        }
        meta_path = self.out_dir / f"manifest_{timestamp}.json"
        meta_path.write_text(json.dumps(meta, indent=2))

        logger.info("Saved %s regional plants (%s total)", len(eu_df), len(df))
        return out_path
