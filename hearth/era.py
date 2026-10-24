"""Film/TV filters Hearth adds to Qloo ranked lists: the resident's era and gentle ratings.

Both are Hearth settings applied through Qloo's documented insights filters
(``filter.release_year.max`` and ``filter.content_rating`` for movie and tv_show), so the
ranked list that picks and swaps come from is already in era and, for the mild_content
need, already gently rated. Scoring a named pick (filter.results.entities) is never filtered,
and "best available" for verdicts still comes from the unfiltered list, so calibrated
relative-fit thresholds keep their meaning.
"""
from __future__ import annotations

from typing import Any

from .constraints.rules import LABEL as RULE_LABEL, MILD_QLOO_RATINGS
from .models import ERA_TYPES, EntityRef, Need, Profile

ERA_LABEL = "Era: Hearth setting"


def ranked_filters(profile: Profile, etype: str) -> dict[str, Any]:
    """Extra /v2/insights params for this person's film/TV ranked lists ({} for other types)."""
    if etype not in ERA_TYPES:
        return {}
    out: dict[str, Any] = {}
    if (era := profile.era) is not None:
        out["filter.release_year.max"] = era.max_year
    if Need.mild_content in profile.needs:
        out["filter.content_rating"] = list(MILD_QLOO_RATINGS)
    return out


def filter_notes(profile: Profile, etype: str) -> list[str]:
    """Evidence lines explaining the filters above."""
    if etype not in ERA_TYPES:
        return []
    notes = []
    if (era := profile.era) is not None:
        notes.append(f"{ERA_LABEL}: {era.explanation}")
    if Need.mild_content in profile.needs:
        notes.append(f"Gentle films: only {', '.join(MILD_QLOO_RATINGS)} ratings considered for picks and swaps "
                     f"({RULE_LABEL}; applied with Qloo's content-rating filter)")
    return notes


def out_of_era(e: EntityRef, profile: Profile) -> str | None:
    """Why an entity falls after the person's era, or None when it fits (or the year is unknown)."""
    era = profile.era
    if era is None or e.type not in ERA_TYPES:
        return None
    y = e.properties.get("release_year")
    if isinstance(y, (int, float)) and int(y) > era.max_year:
        who = f"{profile.name}'s" if profile.name else "their"
        return f"released {int(y)}, after {who} era (films up to {era.max_year}). {ERA_LABEL}"
    return None
