"""Weekly plan for one resident. Deterministic: same profile + same Qloo answers -> same plan."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from pydantic import BaseModel, Field

from ..constraints import (Dish, RuleResult, check_entity, cuisine_key, dishes_for, entity_filter,
                           passes)
from ..constraints.rules import CUISINE_NAMES, unasked_dark
from ..era import filter_notes, ranked_filters
from ..models import EntityRef, Profile
from ..qloo import QlooClient
from ..verifier import Candidate, CheckResult, Resolution, ResolutionStatus, assess, top_for

CUISINE_PREFIX = "urn:tag:genre:place:restaurant:"
RESTAURANT_TAG = "urn:tag:genre:place:restaurant"
WIDE_RADIUS = 80_000  # metres

A = "urn:entity:artist"
M = "urn:entity:movie"
TV = "urn:entity:tv_show"
B = "urn:entity:book"
P = "urn:entity:place"

# A full day in a care home: morning, lunch, afternoon, evening. Fixed so plans are reproducible
# and printable. (day, slot, Qloo type or None for a Hearth-only slot)
SCHEDULE: list[tuple[str, str, str | None]] = [
    ("Monday", "morning_music", A), ("Monday", "meal_theme", P), ("Monday", "reading", B), ("Monday", "film_night", M),
    ("Tuesday", "morning_tv", TV), ("Tuesday", "meal_theme", P), ("Tuesday", "music_session", A), ("Tuesday", "tv_evening", TV),
    ("Wednesday", "outing", P), ("Wednesday", "meal_theme", P), ("Wednesday", "reading", B), ("Wednesday", "film_night", M),
    ("Thursday", "morning_music", A), ("Thursday", "meal_theme", P), ("Thursday", "music_session", A), ("Thursday", "tv_evening", TV),
    ("Friday", "morning_tv", TV), ("Friday", "meal_theme", P), ("Friday", "visitors", None), ("Friday", "film_night", M),
    ("Saturday", "outing", P), ("Saturday", "meal_theme", P), ("Saturday", "music_session", A), ("Saturday", "film_night", M),
    ("Sunday", "morning_music", A), ("Sunday", "meal_theme", P), ("Sunday", "rest", None), ("Sunday", "tv_evening", TV),
]

# When Qloo has nothing suitable for a slot (few books or shows pass the care rules), fall back
# to a domain that almost always has picks, in a slot that doesn't clash on the same day.
FALLBACK: dict[str, tuple[str, str]] = {
    "reading": ("listening", A),
    "morning_tv": ("morning_music", A),
    "tv_evening": ("film_night", M),
}

STATIC = {
    "visitors": ("Family & visitors", "kept free for visits; share this week's plan with family so they can join in"),
    "rest": ("Quiet time & reminiscence", "a gentle afternoon; look through photos or play a few favourites from the playlist"),
}


class PlanItem(BaseModel):
    day: str
    slot: str
    title: str
    entity: EntityRef | None = None
    check: CheckResult | None = None
    rules: list[RuleResult] = Field(default_factory=list)
    dishes: list[Dish] = Field(default_factory=list)
    evidence_places: list[str] = Field(default_factory=list)
    cuisine: str | None = None  # cuisine key for meal themes (used to swap a theme)
    notes: list[str] = Field(default_factory=list)


class WeeklyPlan(BaseModel):
    resident_id: str | None
    name: str
    items: list[PlanItem]
    notes: list[str] = Field(default_factory=list)
    source_note: str = ("Picks and evidence come from Qloo. Care checks (labelled 'Hearth rule, not "
                        "Qloo'), the menu library and the schedule are Hearth's.")


def rank_cuisines(places: list[EntityRef]) -> list[tuple[str, str, float, list[str]]]:
    """Pure: (cuisine key, display name, summed affinity, example places) from Qloo-ranked places."""
    score: dict[str, float] = defaultdict(float)
    names: dict[str, str] = {}
    examples: dict[str, list[str]] = defaultdict(list)
    for p in places:
        aff = float(p.properties.get("affinity") or 0.0)
        for t in p.tags:
            if t.id.startswith(CUISINE_PREFIX):
                k = cuisine_key(t.id)
                score[k] += aff
                names[k] = CUISINE_NAMES.get(k) or t.name or k
                if p.name not in examples[k]:
                    examples[k].append(p.name)
    ranked = sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(k, names[k], round(s, 4), examples[k][:3]) for k, s in ranked]


_NOT_OUTING = ("store", "shop", "office", "boutique", "salon", "bank", "agency", "dealer", "clinic", "broker",
               "insurance", "estate", "lawyer", "accountant", "consultant", "contractor", "repair", "wholesaler",
               "supplier", "studio_rental", "coworking")


def _not_an_outing(e: EntityRef) -> bool:
    """Place genre/category tags that make a poor care-home outing (live London top lists include shops)."""
    for t in e.tags:
        if t.id.startswith(("urn:tag:genre:place:", "urn:tag:category:place:")) and not t.id.startswith(CUISINE_PREFIX):
            last = t.id.rsplit(":", 1)[-1]
            if any(k in last for k in _NOT_OUTING):
                return True
    return False


def _pick_activity(ranked: list[EntityRef], profile: Profile, facts: Mapping[str, Mapping[str, Any]],
                   used: set[str], slot: str, day: str, *, skip_cuisine_only: bool = False,
                   best_ranked: list[EntityRef] | None = None, filter_note: list[str] | None = None) -> PlanItem:
    ok = entity_filter(profile.needs, facts)
    item = _first_pick(ranked, profile, facts, used, slot, day, ok, skip_cuisine_only, best_ranked,
                       filter_note, guard=True)
    if item is None:  # every suitable title was darker than their favourites: allow, and say so
        item = _first_pick(ranked, profile, facts, used, slot, day, ok, skip_cuisine_only, best_ranked,
                           filter_note, guard=False)
    if item is not None:
        return item
    return PlanItem(day=day, slot=slot, title="(no suitable pick found)",
                    notes=["no Qloo result passed this resident's care rules"
                           + (" and era setting" if filter_note else "") + "; staff to choose", *(filter_note or [])])


def _first_pick(ranked, profile, facts, used, slot, day, ok, skip_cuisine_only, best_ranked, filter_note,
                *, guard: bool) -> PlanItem | None:
    for e in ranked:
        if e.id in used or e.id in profile.disliked:
            continue
        dark = unasked_dark(e, profile)
        if guard and dark:
            continue
        if skip_cuisine_only and e.tags and all(t.id.startswith(CUISINE_PREFIX) for t in e.tags):
            continue  # outings: prefer non-restaurant places
        if skip_cuisine_only and _not_an_outing(e):
            continue  # shops, offices and the like are not outings
        rules = check_entity(e, profile.needs, facts.get(e.id))
        if not passes(rules):
            continue
        cand = Candidate(name=e.name, domain=e.type.rsplit(":", 1)[-1], entity_id=e.id)
        res = Resolution(status=ResolutionStatus.resolved, entity=e)
        check = assess(cand, res, e, ranked, profile, swap_filter=ok, best_ranked=best_ranked,
                       notes=filter_note or ())
        used.add(e.id)
        notes = [*(filter_note or []), *(f"staff to confirm: {r.reason}" for r in rules if r.outcome.value == "unknown")]
        if dark:
            notes.append(f"staff to preview: {dark}")
        if any(x.id == e.id for x in profile.entities):
            notes.insert(0, "a known favourite (already in their profile)")
        return PlanItem(day=day, slot=slot, title=e.name, entity=e, check=check, rules=rules, notes=notes)
    return None


async def weekly_plan(client: QlooClient, profile: Profile, *,
                      facts: Mapping[str, Mapping[str, Any]] | None = None,
                      place_extra: dict | None = None,
                      skip_ids: list[str] | None = None,
                      skip_cuisines: list[str] | None = None) -> WeeklyPlan:
    """``skip_ids`` / ``skip_cuisines`` let staff swap a pick: the slot moves to the next one."""
    facts = facts or {}
    skip_c = set(skip_cuisines or [])
    ranked: dict[str, list[EntityRef]] = {}
    best: dict[str, list[EntityRef]] = {}     # unfiltered lists for "best available" (film/TV)
    fnotes: dict[str, list[str]] = {}
    types = {t for _, _, t in SCHEDULE if t} | {t for _, t in FALLBACK.values()}
    for etype in sorted(types):
        if etype not in ranked:
            extra = place_extra if etype == P else None
            if hf := ranked_filters(profile, etype):
                # Picks and swaps from Qloo's list narrowed to the era / gentle ratings (Hearth settings);
                # verdicts still measured against the unfiltered best so thresholds keep their meaning.
                ranked[etype] = await top_for(client, profile, etype, take=20, extra={**(extra or {}), **hf})
                best[etype] = await top_for(client, profile, etype, take=20, extra=extra)
                fnotes[etype] = filter_notes(profile, etype)
            else:
                ranked[etype] = await top_for(client, profile, etype, take=20, extra=extra)
    # Meal themes: restaurants Qloo ranks for this person (one call); falls back to all places.
    meals = await top_for(client, profile, "urn:entity:place", take=50,
                          extra={**(place_extra or {}), "filter.tags": RESTAURANT_TAG})
    cuisines = [c for c in rank_cuisines(meals or ranked["urn:entity:place"])
                if dishes_for(c[0], profile.needs) and c[0] not in skip_c]
    plan_notes: list[str] = []
    radius = (place_extra or {}).get("filter.location.radius")
    if len(cuisines) < 3 and radius and radius < WIDE_RADIUS:
        # Small towns: few restaurants on Qloo nearby, so read the region's food scene instead.
        wide = await top_for(client, profile, "urn:entity:place", take=50,
                             extra={**(place_extra or {}), "filter.location.radius": WIDE_RADIUS,
                                    "filter.tags": RESTAURANT_TAG})
        have = {c[0] for c in cuisines}
        cuisines += [c for c in rank_cuisines(wide)
                     if c[0] not in have and dishes_for(c[0], profile.needs) and c[0] not in skip_c]
        plan_notes.append(f"Few restaurants near the home on Qloo, so lunch themes use places within "
                          f"{WIDE_RADIUS // 1000} km.")
    used: set[str] = set(skip_ids or [])
    meal_i = 0
    items: list[PlanItem] = []

    def activity(day: str, slot: str, etype: str) -> PlanItem:
        return _pick_activity(ranked[etype], profile, facts, used, slot, day,
                              skip_cuisine_only=(slot == "outing"), best_ranked=best.get(etype),
                              filter_note=fnotes.get(etype))

    for day, slot, etype in SCHEDULE:
        if etype is None:
            title, note = STATIC[slot]
            items.append(PlanItem(day=day, slot=slot, title=title, notes=[note]))
        elif slot == "meal_theme":
            if cuisines:
                key, name, score, ex = cuisines[meal_i % len(cuisines)]
                items.append(PlanItem(
                    day=day, slot=slot, title=f"{name} lunch", cuisine=key,
                    dishes=dishes_for(key, profile.needs), evidence_places=ex,
                    notes=[f"theme from places Qloo ranks highest for this profile (sum affinity {score})",
                           "dishes filtered by Hearth rules, not Qloo"]))
            else:
                items.append(PlanItem(day=day, slot=slot, title="(kitchen's choice)",
                                      notes=["no Qloo cuisine signal with suitable dishes in the menu library"]))
            meal_i += 1
        else:
            it = activity(day, slot, etype)
            if it.entity is None and slot in FALLBACK:
                alt = activity(day, *FALLBACK[slot])
                if alt.entity is not None:
                    it = alt
            items.append(it)
    return WeeklyPlan(resident_id=profile.resident_id, name=profile.name, items=items, notes=plan_notes)
