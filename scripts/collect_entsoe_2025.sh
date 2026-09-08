#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

export $(grep -v '^#' .env | xargs)

python3 -m energy_collect.cli entsoe --year 2025 --all-zones --resume

python3 -m energy_collect.cli validate --year 2025
