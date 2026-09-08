"""Map GEM Country/area names to ISO2 codes used in zones.yaml."""

from __future__ import annotations

# GEM spellings -> ISO2 (covers ENTSO-E coupling region in config/zones.yaml)
GEM_COUNTRY_TO_ISO2: dict[str, str] = {
    "Albania": "AL",
    "Austria": "AT",
    "Belgium": "BE",
    "Bosnia and Herzegovina": "BA",
    "Bulgaria": "BG",
    "Croatia": "HR",
    "Czech Republic": "CZ",
    "Denmark": "DK",
    "Estonia": "EE",
    "Finland": "FI",
    "France": "FR",
    "Germany": "DE",
    "Greece": "GR",
    "Hungary": "HU",
    "Ireland": "IE",
    "Italy": "IT",
    "Latvia": "LV",
    "Lithuania": "LT",
    "Luxembourg": "LU",
    "Montenegro": "ME",
    "Netherlands": "NL",
    "North Macedonia": "MK",
    "Norway": "NO",
    "Poland": "PL",
    "Portugal": "PT",
    "Romania": "RO",
    "Serbia": "RS",
    "Slovakia": "SK",
    "Slovenia": "SI",
    "Spain": "ES",
    "Sweden": "SE",
    "Switzerland": "CH",
    "United Kingdom": "GB",
}


def gem_country_to_iso2(name: str) -> str | None:
    return GEM_COUNTRY_TO_ISO2.get(str(name).strip())


def gem_region_country_names() -> set[str]:
    return set(GEM_COUNTRY_TO_ISO2)
