from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
from entsoe import Client, NoDataError, RateLimitError, InvalidParameterError

from energy_collect.collectors.base import BaseCollector, CollectionJob
from energy_collect.config import AppConfig
from energy_collect.storage.manifest import Manifest
from energy_collect.storage.parquet import parquet_path, write_parquet
from energy_collect.utils.rate_limiter import RateLimiter
from energy_collect.utils.zones import BorderPair, border_pairs, month_ranges, year_range

logger = logging.getLogger(__name__)


class ENTSOECollector(BaseCollector):
    def __init__(self, config: AppConfig, manifest: Manifest) -> None:
        if not config.api_key:
            raise ValueError(
                "ENTSOE_API_KEY not set. Add it to .env or export it in your shell."
            )
        self.config = config
        self.manifest = manifest
        self.client = Client(api_key=config.api_key)
        self.rate_limiter = RateLimiter(
            requests_per_minute=config.rate_limit["requests_per_minute"]
        )
        self.zone_map = {z["code"]: z for z in config.zones}

    def plan_jobs(
        self,
        *,
        datasets: list[str] | None,
        zones: list[str] | None,
        year: int,
    ) -> list[CollectionJob]:
        selected_datasets = datasets or list(self.config.datasets.keys())
        selected_zones = zones or list(self.zone_map.keys())
        jobs: list[CollectionJob] = []

        for ds_name in selected_datasets:
            ds = self.config.datasets[ds_name]
            if ds["scope"] == "zone":
                start, end = year_range(year)
                for zone in selected_zones:
                    jobs.append(
                        CollectionJob(
                            dataset=ds_name,
                            scope_key=zone,
                            period_start=start,
                            period_end=end,
                            params={"zone": zone},
                        )
                    )
            elif ds["scope"] == "border_pair":
                pairs = border_pairs(self.config.zones)
                if zones:
                    zone_set = set(zones)
                    pairs = [
                        p
                        for p in pairs
                        if p.from_zone in zone_set or p.to_zone in zone_set
                    ]
                for pair in pairs:
                    if ds.get("chunk") == "month":
                        for start, end in month_ranges(year):
                            jobs.append(
                                CollectionJob(
                                    dataset=ds_name,
                                    scope_key=f"{pair.from_zone}>{pair.to_zone}",
                                    period_start=start,
                                    period_end=end,
                                    params={
                                        "from_zone": pair.from_zone,
                                        "to_zone": pair.to_zone,
                                    },
                                )
                            )
                    else:
                        start, end = year_range(year)
                        jobs.append(
                            CollectionJob(
                                dataset=ds_name,
                                scope_key=f"{pair.from_zone}>{pair.to_zone}",
                                period_start=start,
                                period_end=end,
                                params={
                                    "from_zone": pair.from_zone,
                                    "to_zone": pair.to_zone,
                                },
                            )
                        )
        return jobs

    def _fetch(self, method_path: str, start: str, end: str, **kwargs: Any) -> pd.DataFrame:
        obj = self.client
        for part in method_path.split("."):
            obj = getattr(obj, part)

        max_attempts = self.config.rate_limit["retry_max_attempts"]
        base_delay = self.config.rate_limit["retry_base_delay_seconds"]
        cooldown = self.config.rate_limit["cooldown_on_429_seconds"]

        for attempt in range(max_attempts):
            self.rate_limiter.wait()
            try:
                df = obj(start, end, **kwargs)
                if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                    raise NoDataError(f"No data for {method_path} {kwargs} {start}-{end}")
                return df
            except RateLimitError:
                logger.warning("Rate limited; cooling down %ss", cooldown)
                time.sleep(cooldown)
            except (NoDataError, InvalidParameterError):
                raise
            except Exception as exc:
                if attempt == max_attempts - 1:
                    raise
                delay = base_delay * (2**attempt)
                logger.warning("Request failed (%s), retry in %ss", exc, delay)
                time.sleep(delay)
        raise RuntimeError(f"Failed after {max_attempts} attempts")

    def run_job(self, job: CollectionJob) -> tuple[int, str]:
        ds = self.config.datasets[job.dataset]
        method = ds["method"]
        params = dict(job.params)

        if ds["scope"] == "zone":
            zone = params.pop("zone")
            df = self._fetch(method, job.period_start, job.period_end, country=zone)
            df = df.copy()
            df["zone"] = zone
        else:
            from_zone = params.pop("from_zone")
            to_zone = params.pop("to_zone")
            df = self._fetch(
                method,
                job.period_start,
                job.period_end,
                country_from=from_zone,
                country_to=to_zone,
            )
            df = df.copy()
            df["from_zone"] = from_zone
            df["to_zone"] = to_zone

        df["dataset"] = job.dataset
        df["period_start"] = job.period_start
        df["period_end"] = job.period_end

        out_path = parquet_path(
            self.config.data_root,
            job.dataset,
            job.scope_key,
            job.period_start,
            job.period_end,
        )
        write_parquet(df, out_path)
        return len(df), str(out_path)

    def collect(
        self,
        *,
        datasets: list[str] | None,
        zones: list[str] | None,
        year: int,
        resume: bool = True,
        dry_run: bool = False,
        retry_failed: bool = False,
    ) -> dict[str, int]:
        jobs = self.plan_jobs(datasets=datasets, zones=zones, year=year)
        stats = {"planned": len(jobs), "success": 0, "failed": 0, "skipped": 0}

        if dry_run:
            logger.info("Dry run: %s jobs planned", len(jobs))
            return stats

        for job in jobs:
            job_id = Manifest.make_job_id(
                job.dataset, job.scope_key, job.period_start, job.period_end
            )

            if retry_failed:
                record = self.manifest.get(job_id)
                if record is None or record.status != "failed":
                    stats["skipped"] += 1
                    continue
            elif self.manifest.should_skip(job_id, resume):
                stats["skipped"] += 1
                continue

            try:
                row_count, file_path = self.run_job(job)
                self.manifest.upsert(
                    job_id=job_id,
                    dataset=job.dataset,
                    scope_key=job.scope_key,
                    period_start=job.period_start,
                    period_end=job.period_end,
                    status="success",
                    row_count=row_count,
                    file_path=file_path,
                )
                stats["success"] += 1
                logger.info(
                    "OK %s %s [%s-%s] rows=%s",
                    job.dataset,
                    job.scope_key,
                    job.period_start,
                    job.period_end,
                    row_count,
                )
            except NoDataError as exc:
                self.manifest.upsert(
                    job_id=job_id,
                    dataset=job.dataset,
                    scope_key=job.scope_key,
                    period_start=job.period_start,
                    period_end=job.period_end,
                    status="skipped",
                    error=str(exc),
                )
                stats["skipped"] += 1
                logger.warning(
                    "No data: %s %s [%s-%s]",
                    job.dataset,
                    job.scope_key,
                    job.period_start,
                    job.period_end,
                )
            except InvalidParameterError as exc:
                self.manifest.upsert(
                    job_id=job_id,
                    dataset=job.dataset,
                    scope_key=job.scope_key,
                    period_start=job.period_start,
                    period_end=job.period_end,
                    status="skipped",
                    error=str(exc),
                )
                stats["skipped"] += 1
                logger.warning(
                    "Unsupported zone/params: %s %s: %s",
                    job.dataset,
                    job.scope_key,
                    exc,
                )
            except Exception as exc:
                self.manifest.upsert(
                    job_id=job_id,
                    dataset=job.dataset,
                    scope_key=job.scope_key,
                    period_start=job.period_start,
                    period_end=job.period_end,
                    status="failed",
                    error=str(exc),
                )
                stats["failed"] += 1
                logger.error(
                    "Failed: %s %s [%s-%s]: %s",
                    job.dataset,
                    job.scope_key,
                    job.period_start,
                    job.period_end,
                    exc,
                )
        return stats
