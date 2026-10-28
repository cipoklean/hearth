"""Health and care rules. These are Hearth rules, not Qloo.

Qloo knows taste; it does not know whether a venue is step-free or a dish is
soft. Every result here carries ``label = "Hearth rule, not Qloo"`` so the UI
never presents a care judgement as if it came from the taste graph.

Facts come from three places, in this order:
  1. ``facts``: staff-entered facts about a venue or film (e.g. step_free)
  2. Qloo entity properties/tags (e.g. duration, content_rating, a nightclub tag)
  3. dish attributes from Hearth's own menu library (hearth/data/dishes.json)
Missing facts give ``unknown`` (staff to confirm), never a silent pass.
"""
from __future__ import annotations

import json
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, Field

from ..models import EntityRef, Need

LABEL = "Hearth rule, not Qloo"
DATA = Path(__file__).resolve().parent.parent / "data" / "dishes.json"

SHORT_FILM_MINUTES = 105
MILD_RATINGS = {"G", "PG", "GP", "TV-G", "TV-PG", "TV-Y", "TV-Y7", "U", "Approved", "Passed"}
# The same ratings as Qloo filter.content_rating values (Qloo's enum has no "U"). Sent with
# film/TV ranked lists for residents with the mild_content need, so picks and swaps are gentle
# before Hearth's own rule runs. Unrated titles drop out of those lists.
MILD_QLOO_RATINGS = ("G", "PG", "GP", "TV-G", "TV-PG", "TV-Y", "TV-Y7", "Approved", "Passed")
STRONG_RATINGS = {"R", "NC-17", "TV-MA", "18+"}
INTENSE_TAG_KEYS = ("horror", "war", "thriller", "slasher")
LOUD_TAG_KEYS = ("nightclub", "heavy_metal", "punk", "rave")
# Venue tags (live Qloo place tags, e.g. urn:tag:ambience:qloo:creepy) that make an outing unsuitable
# for someone who needs gentle content.
DARK_PLACE_KEYS = ("true_crime", "creepy", "grim", "horror", "haunted", "dungeon", "macabre", "torture")
STEP_FREE_KEYS = ("wheelchair_accessible_entrance",)
FOOD_NEEDS = {Need.soft_food, Need.low_salt, Need.low_sugar, Need.vegetarian}


class Outcome(str, Enum):
    pass_ = "pass"
    fail = "fail"
    unknown = "unknown"


class RuleResult(BaseModel):
    need: Need
    outcome: Outcome
    reason: str
    label: str = LABEL


class Dish(BaseModel):
    name: str
    cuisine: str
    soft: bool = False
    low_salt: bool = False
    low_sugar: bool = False
    vegetarian: bool = False


@lru_cache(maxsize=1)
def dish_library() -> list[Dish]:
    raw = json.loads(DATA.read_text())
    return [Dish(**d) for d in raw["dishes"]]


# Qloo restaurant tags are fine-grained (and in big cities often venue types like "cafe" or
# "gastropub"); Hearth maps them onto the cuisines its menu library covers. Unmapped keys
# (bars, food courts...) have no dishes and are skipped by the planner.
CUISINE_ALIASES = {
    "tea_house": "tea_room", "tea_and_coffee_shop": "tea_room", "cafe": "tea_room", "coffee_shop": "tea_room",
    "cake_shop": "tea_room", "bakery": "tea_room", "art_cafe": "tea_room", "breakfast": "tea_room",
    "sandwich_shop": "tea_room", "brunch": "tea_room",
    "gastropub": "british", "english": "british", "pub": "british", "fish_and_chips": "british",
    "modern_british": "british", "scottish": "british", "irish": "british",
    "fine_dining": "modern_european", "european": "modern_european", "brasserie": "french",
    "bistro": "french", "haute_french": "french", "pizza": "italian", "trattoria": "italian",
    "tapas": "spanish", "dim_sum": "chinese", "cantonese": "chinese", "sichuan": "chinese",
    "curry": "indian", "north_indian": "indian", "south_indian": "indian",
    "hamburger": "american", "steakhouse": "american", "diner": "american", "southern": "american",
    "greek": "mediterranean", "middle_eastern": "mediterranean", "lebanese": "mediterranean",
    "nigerian": "west_african", "ghanaian": "west_african", "jamaican": "caribbean",
    "fish": "seafood", "oyster_bar": "seafood",
}
CUISINE_NAMES = {
    "tea_room": "Afternoon tea", "british": "British classics", "modern_european": "Modern European",
    "french": "French bistro", "italian": "Italian", "spanish": "Spanish", "chinese": "Cantonese",
    "indian": "Indian", "american": "American diner", "mediterranean": "Mediterranean",
    "west_african": "West African", "caribbean": "Caribbean", "seafood": "Seaside",
}


def cuisine_key(tag_id: str) -> str:
    k = tag_id.rsplit(":", 1)[-1]
    return CUISINE_ALIASES.get(k, k)


def _tag_keys(e: EntityRef) -> set[str]:
    return {cuisine_key(t.id) for t in e.tags}


def _r(need: Need, outcome: Outcome, reason: str) -> RuleResult:
    return RuleResult(need=need, outcome=outcome, reason=reason)


def check_dish(dish: Dish, needs: Iterable[Need]) -> list[RuleResult]:
    out = []
    for n in needs:
        if n not in FOOD_NEEDS:
            continue
        ok = {Need.soft_food: dish.soft, Need.low_salt: dish.low_salt,
              Need.low_sugar: dish.low_sugar, Need.vegetarian: dish.vegetarian}[n]
        out.append(_r(n, Outcome.pass_ if ok else Outcome.fail,
                      f"{dish.name}: {'meets' if ok else 'does not meet'} {n.value.replace('_', ' ')}"))
    return out


def check_entity(e: EntityRef, needs: Iterable[Need], facts: Mapping[str, Any] | None = None) -> list[RuleResult]:
    """Rules for an activity entity (artist, movie, tv_show, place, destination, ...)."""
    facts = facts or {}
    kind = e.type.rsplit(":", 1)[-1]
    keys = _tag_keys(e)
    out: list[RuleResult] = []
    for n in needs:
        if n is Need.wheelchair_access and kind in {"place", "destination"}:
            v = facts.get("step_free")
            if v is None and keys & set(STEP_FREE_KEYS):
                out.append(_r(n, Outcome.pass_, "wheelchair-accessible entrance listed in venue data"))
            elif v is None:
                out.append(_r(n, Outcome.unknown, "step-free access not recorded; staff to confirm"))
            else:
                out.append(_r(n, Outcome.pass_ if v else Outcome.fail,
                              "step-free access confirmed" if v else "recorded as not step-free"))
        elif n is Need.quiet_setting:
            if keys & set(LOUD_TAG_KEYS):
                out.append(_r(n, Outcome.fail, "tagged as a loud genre/venue"))
            elif kind in {"place", "destination"}:
                v = facts.get("quiet")
                if v is None:
                    out.append(_r(n, Outcome.unknown, "noise level not recorded; staff to confirm"))
                else:
                    out.append(_r(n, Outcome.pass_ if v else Outcome.fail,
                                  "recorded as quiet" if v else "recorded as noisy"))
            else:
                out.append(_r(n, Outcome.pass_, "session volume set by staff"))
        elif n is Need.short_duration and kind in {"movie", "tv_show"}:
            mins = e.properties.get("duration") or facts.get("duration")
            if mins is None:
                out.append(_r(n, Outcome.unknown, "running time unknown"))
            else:
                ok = float(mins) <= SHORT_FILM_MINUTES
                out.append(_r(n, Outcome.pass_ if ok else Outcome.fail,
                              f"{int(float(mins))} min ({'within' if ok else 'over'} {SHORT_FILM_MINUTES})"))
        elif n is Need.mild_content and kind in {"movie", "tv_show"}:
            rating = str(e.properties.get("content_rating") or facts.get("content_rating") or "")
            intense = sorted(keys & set(INTENSE_TAG_KEYS))
            if rating in STRONG_RATINGS:
                out.append(_r(n, Outcome.fail, f"rated {rating}"))
            elif intense:
                out.append(_r(n, Outcome.fail, f"{intense[0]} genre"
                              + (f", although rated {rating}" if rating else "")))
            elif rating in MILD_RATINGS:
                out.append(_r(n, Outcome.pass_, f"rated {rating}"))
            else:
                out.append(_r(n, Outcome.unknown, f"rating {rating or 'unknown'}; staff to preview"))
        elif n is Need.mild_content and kind in {"place", "destination"}:
            dark = sorted(keys & set(DARK_PLACE_KEYS))
            if dark:
                out.append(_r(n, Outcome.fail, f"dark theme ({dark[0].replace('_', ' ')})"))
        elif n is Need.hearing_support and kind in {"movie", "tv_show"}:
            v = facts.get("subtitles")
            out.append(_r(n, Outcome.pass_ if v else Outcome.unknown,
                          "subtitles available" if v else "turn on subtitles / hearing loop"))
        elif n in FOOD_NEEDS and kind in {"place", "destination"}:
            v = facts.get(f"{n.value}_options")
            out.append(_r(n, Outcome.unknown if v is None else (Outcome.pass_ if v else Outcome.fail),
                          f"{n.value.replace('_', ' ')} options " +
                          ("not recorded; call ahead" if v is None else ("available" if v else "not available"))))
    return out


def passes(results: Iterable[RuleResult]) -> bool:
    """Hard filter: nothing failed (unknowns are allowed but must be shown)."""
    return all(r.outcome is not Outcome.fail for r in results)


def entity_filter(needs: Iterable[Need], facts_for: Mapping[str, Mapping[str, Any]] | None = None):
    """Build a verifier swap_filter from a person's needs."""
    needs = list(needs)
    facts_for = facts_for or {}

    def _ok(e: EntityRef) -> bool:
        return passes(check_entity(e, needs, facts_for.get(e.id)))
    return _ok


def dishes_for(cuisine: str, needs: Iterable[Need], limit: int = 3) -> list[Dish]:
    needs = list(needs)
    return [d for d in dish_library() if d.cuisine == cuisine and passes(check_dish(d, needs))][:limit]


# Suggesting films nobody asked for: dark genres (and strong ratings) only when the person's own
# favourites already show them. Live: a resident whose favourites were Fela Kuti and a jollof
# restaurant got "The Fool" (2014), a violent crime film, as film night. Named picks are still
# scored as asked; this only steers what Hearth *suggests*.
DARK_FILM_KEYS = ("crime", "horror", "thriller", "war", "gangster", "slasher", "splatter", "exploitation",
                  "torture", "gore", "serial_killer", "mafia")


def _dark_keys(tag_ids) -> set[str]:
    out = set()
    for tid in tag_ids:
        if tid.startswith("urn:tag:genre:") or tid.startswith("urn:tag:subgenre:"):
            last = tid.rsplit(":", 1)[-1]
            out.update(k for k in DARK_FILM_KEYS if k in last)
    return out


def unasked_dark(e: EntityRef, profile) -> str | None:
    """Why a film/TV suggestion is darker than anything in this person's favourites, else None."""
    if e.type.rsplit(":", 1)[-1] not in {"movie", "tv_show"}:
        return None
    if any(x.id == e.id for x in profile.entities):
        return None
    liked = profile.known_tags()
    new = _dark_keys(t.id for t in e.tags) - _dark_keys(liked)
    if new:
        return f"{', '.join(sorted(k.replace('_', ' ') for k in new))} film, and none of their favourites are ({LABEL})"
    rating = str(e.properties.get("content_rating") or "")
    if rating in STRONG_RATINGS and not any(str(x.properties.get("content_rating") or "") in STRONG_RATINGS
                                            for x in profile.entities if x.weight > 0):
        return f"rated {rating}, stronger than their favourites ({LABEL})"
    return None

