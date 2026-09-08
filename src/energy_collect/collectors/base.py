from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class CollectionJob:
    dataset: str
    scope_key: str
    period_start: str
    period_end: str
    params: dict[str, Any]


class BaseCollector(ABC):
    @abstractmethod
    def plan_jobs(
        self,
        *,
        datasets: list[str] | None,
        zones: list[str] | None,
        year: int,
    ) -> list[CollectionJob]:
        raise NotImplementedError

    @abstractmethod
    def run_job(self, job: CollectionJob) -> tuple[int, str]:
        """Execute one job. Returns (row_count, file_path)."""
        raise NotImplementedError
