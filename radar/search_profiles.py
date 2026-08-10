from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class SearchProfile:
    name: str
    enabled: bool = True
    queries: list[str] = field(default_factory=list)
    positive_terms: list[str] = field(default_factory=list)
    negative_terms: list[str] = field(default_factory=list)
    preferred_nmck_min: float | None = None
    preferred_nmck_max: float | None = None
    hard_nmck_min: float | None = None
    minimum_days_to_deadline: int | None = None
    preferred_days_to_deadline: int | None = None
    commodity_penalty: int = 10
    complexity_bonus_terms: list[str] = field(default_factory=list)
    exclusion_terms: list[str] = field(default_factory=list)


def load_search_profiles(path: str | Path = "config/search_profiles.yaml") -> list[SearchProfile]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    profiles_data: list[dict[str, Any]] = data.get("profiles", data if isinstance(data, list) else [])
    return [SearchProfile(**item) for item in profiles_data]


def select_profiles(
    profiles: list[SearchProfile],
    selected_name: str | None = None,
    all_profiles: bool = False,
) -> list[SearchProfile]:
    enabled = [profile for profile in profiles if profile.enabled]
    if all_profiles or not selected_name:
        return enabled if all_profiles else enabled[:1]
    selected = [profile for profile in enabled if profile.name == selected_name]
    if not selected:
        raise ValueError(f"Unknown or disabled radar profile: {selected_name}")
    return selected

