"""Group pick: one activity for several residents, maximising fit across them.

Objective (lexicographic, deterministic):
  1. most residents at or above the 'weak' fit line
  2. highest mean relative fit
  3. highest minimum relative fit
  4. entity id (tie-break)
Anyone below the line is named as left out and given their own alternative.
An option that fails any attendee's care rule is excluded (and reported).
"""
from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, Field

from ..constraints import check_entity, passes
from ..era import ERA_LABEL, out_of_era, ranked_filters
from ..models import EntityRef, Profile, Tag
from ..qloo import QlooClient
from ..verifier import (DEFAULT_THRESHOLDS, Candidate, Resolution, ResolutionStatus, Thresholds, Verdict,
                        classify, domain_to_type, relative_fit, resolve, score_entities,
                        shared_tags, top_for)
from ..verifier.core import affinity_of


class ResidentFit(BaseModel):
    resident_id: str | None
    name: str
    relative_fit: float
    qloo_affinity: float
    verdict: str
    shared_tags: list[Tag] = Field(default_factory=list)


class LeftOut(BaseModel):
    resident_id: str | None
    name: str
    relative_fit: float
    alternative: EntityRef | None
    alternative_fit: float | None = None
    reason: str


class Excluded(BaseModel):
    entity: EntityRef
    reason: str


class GroupPick(BaseModel):
    domain: str
    pick: EntityRef | None
    fits: list[ResidentFit] = Field(default_factory=list)
    left_out: list[LeftOut] = Field(default_factory=list)
    excluded: list[Excluded] = Field(default_factory=list)
    unresolved: list[Resolution] = Field(default_factory=list)
    considered: int = 0
    notes: list[str] = Field(default_factory=list)


def choose(pool: list[EntityRef], rel: dict[str, dict[str, float]], profiles: list[Profile],
           th: Thresholds = DEFAULT_THRESHOLDS) -> EntityRef | None:
    """Pure: pick the pool item with the best group objective. rel[profile_key][entity_id]."""
    def key(e: EntityRef):
        fits = [rel[_pk(p)].get(e.id, 0.0) for p in profiles]
        weak = th.for_type(e.type).weak
        n_ok = sum(f >= weak for f in fits)
        return (n_ok, sum(fits) / len(fits), min(fits), _neg(e.id))
    return max(pool, key=key) if pool else None


def _neg(s: str) -> tuple[int, ...]:
    return tuple(-ord(c) for c in s)  # smaller id wins ties under max()


def _pk(p: Profile) -> str:
    return p.resident_id or p.name


async def group_pick(client: QlooClient, profiles: list[Profile], domain: str, *,
                     candidates: list[Candidate] | None = None,
                     facts: Mapping[str, Mapping[str, Any]] | None = None,
                     per_person: int = 5, th: Thresholds = DEFAULT_THRESHOLDS,
                     place_extra: dict | None = None) -> GroupPick:
    if not profiles:
        raise ValueError("group_pick needs at least one resident")
    facts = facts or {}
    etype = domain_to_type(domain)
    out = GroupPick(domain=domain, pick=None)

    tops: dict[str, list[EntityRef]] = {}   # what each person's picks/alternatives come from
    bests: dict[str, list[EntityRef]] = {}  # unfiltered, for "best available"
    for p in profiles:
        extra = place_extra if etype == "urn:entity:place" else None
        take = max(per_person, 20)
        if hf := ranked_filters(p, etype):  # era / gentle ratings (Hearth settings) for film and TV
            tops[_pk(p)] = await top_for(client, p, etype, take=take, extra={**(extra or {}), **hf})
            bests[_pk(p)] = await top_for(client, p, etype, take=take, extra=extra)
        else:
            tops[_pk(p)] = bests[_pk(p)] = await top_for(client, p, etype, take=take, extra=extra)
    for p in profiles:
        if p.era is not None and etype in ("urn:entity:movie", "urn:entity:tv_show"):
            out.notes.append(f"{ERA_LABEL} for {p.name} ({p.era.explanation})")

    pool: dict[str, EntityRef] = {}
    if candidates:
        for c in candidates:
            res = await resolve(client, c)
            if res.status is ResolutionStatus.resolved and res.entity:
                pool[res.entity.id] = res.entity
            else:
                out.unresolved.append(res)
    else:
        for p in profiles:
            for e in tops[_pk(p)][:per_person]:
                pool.setdefault(e.id, e)

    # Qloo affinity of every pool item for every resident (one call per resident)
    rel: dict[str, dict[str, float]] = {}
    aff: dict[str, dict[str, float]] = {}
    for p in profiles:
        scored = await score_entities(client, p, etype, list(pool))
        for eid, e in scored.items():
            if not pool[eid].tags and e.tags:
                pool[eid] = e
        best = max([0.0, *(affinity_of(e) for e in bests[_pk(p)]), *(affinity_of(e) for e in scored.values())])
        aff[_pk(p)] = {eid: affinity_of(e) for eid, e in scored.items()}
        rel[_pk(p)] = {eid: relative_fit(a, best) for eid, a in aff[_pk(p)].items()}
        for eid in p.disliked:
            if eid in rel[_pk(p)]:
                rel[_pk(p)][eid] = 0.0

    allowed: list[EntityRef] = []
    for e in sorted(pool.values(), key=lambda x: x.id):
        failing = [f"{p.name}: {r.reason}" for p in profiles
                   for r in check_entity(e, p.needs, facts.get(e.id)) if r.outcome.value == "fail"]
        late = [(p.name, why) for p in profiles if (why := out_of_era(e, p)) is not None]
        if late and not candidates:
            # Suggested options must sit in every attendee's era; staff-named options are kept and flagged.
            out.excluded.append(Excluded(entity=e, reason="; ".join(f"{n}: {w}" for n, w in late)))
            continue
        if late:
            out.notes.extend(f"{e.name}: {w}" for _, w in late)
        if failing:
            out.excluded.append(Excluded(entity=e, reason="; ".join(failing) + " (Hearth rule, not Qloo)"))
        else:
            allowed.append(e)
    out.considered = len(pool)
    pick = choose(allowed, rel, profiles, th)
    out.pick = pick
    if pick is None:
        return out

    for p in profiles:
        k = _pk(p)
        f = rel[k].get(pick.id, 0.0)
        out.fits.append(ResidentFit(resident_id=p.resident_id, name=p.name, relative_fit=f,
                                    qloo_affinity=aff[k].get(pick.id, 0.0), verdict=classify(f, th, affinity=aff[k].get(pick.id), etype=etype).value,
                                    shared_tags=shared_tags(pick, p)))
        if classify(f, th, affinity=aff[k].get(pick.id), etype=etype) is Verdict.poor:
            alt, alt_fit = None, None
            for e in tops[k]:
                if e.id == pick.id or e.id in p.disliked:
                    continue
                if passes(check_entity(e, p.needs, facts.get(e.id))) and out_of_era(e, p) is None:
                    alt, alt_fit = e, relative_fit(affinity_of(e), max(affinity_of(x) for x in bests[k]))
                    break
            out.left_out.append(LeftOut(
                resident_id=p.resident_id, name=p.name, relative_fit=f, alternative=alt, alternative_fit=alt_fit,
                reason=f"{pick.name} is a poor fit for {p.name}"
                       + (f"; offer {alt.name} as a 1:1 or small-group alternative" if alt else "")))
    return out
