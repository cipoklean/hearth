"""Weekly plan for one resident. Deterministic: same profile + same Qloo answers -> same plan."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from pydantic import BaseModel, Field

from ..constraints import (Dish, RuleResult, check_entity, cuisine_key, dishes_for, entity_filter,
                           passes)
from ..models import EntityRef, Profile
from ..qloo import QlooClient
from ..verifier import Candidate, CheckResult, Resolution, ResolutionStatus, assess, top_for

CUISINE_PREFIX = "urn:tag:genre:place:restaurant:"

# (day, slot, Qloo type) - fixed so plans are reproducible and printable
SCHEDULE: list[tuple[str, str, str]] = [
    ("Monday", "meal_theme", "urn:entity:place"),
    ("Tuesday", "music_session", "urn:entity:artist"),
    ("Wednesday", "meal_theme", "urn:entity:place"),
    ("Thursday", "film_night", "urn:entity:movie"),
    ("Saturday", "outing", "urn:entity:place"),
]


class PlanItem(BaseModel):
    day: str
    slot: str
    title: str
    entity: EntityRef | None = None
    check: CheckResult | None = None
    rules: list[RuleResult] = Field(default_factory=list)
    dishes: list[Dish] = Field(default_factory=list)
    evidence_places: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class WeeklyPlan(BaseModel):
    resident_id: str | None
    name: str
    items: list[PlanItem]
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
                names[k] = t.name or k
                examples[k].append(p.name)
    ranked = sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(k, names[k], round(s, 4), examples[k][:3]) for k, s in ranked]


def _pick_activity(ranked: list[EntityRef], profile: Profile, facts: Mapping[str, Mapping[str, Any]],
                   used: set[str], slot: str, day: str, *, skip_cuisine_only: bool = False) -> PlanItem:
    ok = entity_filter(profile.needs, facts)
    for e in ranked:
        if e.id in used or e.id in profile.disliked:
            continue
        if skip_cuisine_only and e.tags and all(t.id.startswith(CUISINE_PREFIX) for t in e.tags):
            continue  # outings: prefer non-restaurant places
        rules = check_entity(e, profile.needs, facts.get(e.id))
        if not passes(rules):
            continue
        cand = Candidate(name=e.name, domain=e.type.rsplit(":", 1)[-1], entity_id=e.id)
        res = Resolution(status=ResolutionStatus.resolved, entity=e)
        check = assess(cand, res, e, ranked, profile, swap_filter=ok)
        used.add(e.id)
        notes = [f"staff to confirm: {r.reason}" for r in rules if r.outcome.value == "unknown"]
        if any(x.id == e.id for x in profile.entities):
            notes.insert(0, "a known favourite (already in their profile)")
        return PlanItem(day=day, slot=slot, title=e.name, entity=e, check=check, rules=rules, notes=notes)
    return PlanItem(day=day, slot=slot, title="(no suitable pick found)",
                    notes=["no Qloo result passed this resident's care rules; staff to choose"])


async def weekly_plan(client: QlooClient, profile: Profile, *,
                      facts: Mapping[str, Mapping[str, Any]] | None = None,
                      place_extra: dict | None = None) -> WeeklyPlan:
    facts = facts or {}
    ranked: dict[str, list[EntityRef]] = {}
    for _, _, etype in SCHEDULE:
        if etype not in ranked:
            extra = place_extra if etype == "urn:entity:place" else None
            ranked[etype] = await top_for(client, profile, etype, take=20, extra=extra)
    cuisines = [c for c in rank_cuisines(ranked["urn:entity:place"])
                if dishes_for(c[0], profile.needs)]
    used: set[str] = set()
    meal_i = 0
    items: list[PlanItem] = []
    for day, slot, etype in SCHEDULE:
        if slot == "meal_theme":
            if meal_i < len(cuisines):
                key, name, score, ex = cuisines[meal_i]
                items.append(PlanItem(
                    day=day, slot=slot, title=f"{name} lunch",
                    dishes=dishes_for(key, profile.needs), evidence_places=ex,
                    notes=[f"theme from places Qloo ranks highest for this profile (sum affinity {score})",
                           "dishes filtered by Hearth rules, not Qloo"]))
            else:
                items.append(PlanItem(day=day, slot=slot, title="(kitchen's choice)",
                                      notes=["no Qloo cuisine signal with suitable dishes in the menu library"]))
            meal_i += 1
        else:
            items.append(_pick_activity(ranked[etype], profile, facts, used, slot, day,
                                        skip_cuisine_only=(slot == "outing")))
    return WeeklyPlan(resident_id=profile.resident_id, name=profile.name, items=items)
