"""The taste checker.

verify(profile, candidates):
  1. resolve each free-text name to a Qloo entity (/search); ambiguous names
     come back for confirmation, no match -> cannot_verify
  2. score fit via /v2/insights (profile signals, filter.results.entities)
  3. attach evidence: Qloo affinity, best available affinity, shared tags
  4. verdict good / weak / poor from *relative* fit (affinity vs the best
     Qloo offers this profile in that domain), so thresholds survive whatever
     absolute scale the real API uses
  5. propose a better-fitting swap from Qloo's ranked list

Pure helpers are separated from the async I/O so they can be unit-tested.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Callable, Iterable

from ..models import EntityRef, Profile, Tag
from ..qloo import QlooClient
from ..qloo.params import DOMAINS, normalize_type
from .models import (Candidate, CheckResult, Evidence, Resolution, ResolutionStatus, Swap,
                     Verdict, VerifyReport)

SwapFilter = Callable[[EntityRef], bool]


@dataclass(frozen=True)
class Thresholds:
    good: float = 0.80   # relative fit
    weak: float = 0.55
    exact_unique_ratio: float = 0.90
    fuzzy_min_ratio: float = 0.60


DEFAULT = Thresholds()
DEFAULT_THRESHOLDS = DEFAULT


# ---- pure helpers ------------------------------------------------------------
def domain_to_type(domain: str) -> str:
    t = normalize_type(domain.strip().lower())
    if t not in DOMAINS.values():
        raise ValueError(f"unknown domain {domain!r}; use one of {sorted(DOMAINS)}")
    return t


def _norm(s: str) -> str:
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in s).split())


def match_candidates(name: str, results: list[EntityRef], th: Thresholds = DEFAULT) -> Resolution:
    """Decide resolved / ambiguous / cannot_verify from /search results."""
    if not results:
        return Resolution(status=ResolutionStatus.cannot_verify, reason="no Qloo entity matches this name")
    n = _norm(name)
    exact = [r for r in results if _norm(r.name) == n]
    if len(exact) == 1:
        return Resolution(status=ResolutionStatus.resolved, entity=exact[0])
    if len(exact) > 1:
        return Resolution(status=ResolutionStatus.ambiguous, options=exact,
                          reason=f"{len(exact)} entities share this name; confirm which one")
    ratios = sorted(((difflib.SequenceMatcher(None, n, _norm(r.name)).ratio(), r) for r in results),
                    key=lambda x: -x[0])
    top, top_r = ratios[0][0], ratios[0][1]
    second = ratios[1][0] if len(ratios) > 1 else 0.0
    if top >= th.exact_unique_ratio and top - second >= 0.1:
        return Resolution(status=ResolutionStatus.resolved, entity=top_r,
                          reason=f"close name match ({top:.2f})")
    close = [r for s, r in ratios if s >= th.fuzzy_min_ratio]
    if close:
        return Resolution(status=ResolutionStatus.ambiguous, options=close,
                          reason="no exact name match; confirm the intended entity")
    return Resolution(status=ResolutionStatus.cannot_verify, reason="no close Qloo name match")


def shared_tags(entity: EntityRef, profile: Profile) -> list[Tag]:
    known = profile.known_tags()
    return [Tag(id=t.id, name=t.name or known.get(t.id, t.id)) for t in entity.tags if t.id in known]


def relative_fit(affinity: float, best: float) -> float:
    if best <= 0:
        return 0.0
    return round(min(1.0, affinity / best), 4)


def classify(rel: float, th: Thresholds = DEFAULT) -> Verdict:
    if rel >= th.good:
        return Verdict.good
    if rel >= th.weak:
        return Verdict.weak
    return Verdict.poor


def profile_signals(profile: Profile) -> dict[str, list[str]]:
    p: dict[str, list[str]] = {}
    if ents := profile.signal_entity_ids():
        p["signal.interests.entities"] = ents
    if tags := profile.signal_tag_ids():
        p["signal.interests.tags"] = tags
    return p


def affinity_of(e: EntityRef) -> float:
    return float(e.properties.get("affinity") or 0.0)


# ---- I/O steps -----------------------------------------------------------------
async def resolve(client: QlooClient, cand: Candidate, th: Thresholds = DEFAULT) -> Resolution:
    etype = domain_to_type(cand.domain)
    if cand.entity_id:
        return Resolution(status=ResolutionStatus.resolved,
                          entity=EntityRef(id=cand.entity_id, name=cand.name, type=etype),
                          reason="confirmed by user")
    results = await client.search(cand.name, types=[etype], take=5)
    results = [r for r in results if r.type == etype] or results
    return match_candidates(cand.name, results, th)


async def score_entities(client: QlooClient, profile: Profile, etype: str,
                         ids: Iterable[str]) -> dict[str, EntityRef]:
    """Qloo affinity of specific entities for this profile (one call)."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        return {}
    sig = profile_signals(profile)
    if not sig:
        return {}
    ents = await client.insights({"filter.type": etype, **sig,
                                  "filter.results.entities": ids, "take": min(50, len(ids))})
    return {e.id: e for e in ents}


async def top_for(client: QlooClient, profile: Profile, etype: str, *, take: int = 10,
                  exclude: Iterable[str] = (), extra: dict | None = None) -> list[EntityRef]:
    sig = profile_signals(profile)
    if not sig:
        return []
    p: dict = {"filter.type": etype, **sig, "take": take}
    excl = list(dict.fromkeys([*exclude, *profile.disliked]))
    if excl:
        p["filter.exclude.entities"] = excl
    if extra:
        p.update(extra)
    return await client.insights(p)


def pick_swap(ranked: list[EntityRef], current_aff: float, best: float, profile: Profile,
              exclude: set[str], swap_filter: SwapFilter | None) -> Swap | None:
    for e in ranked:
        if e.id in exclude:
            continue
        a = affinity_of(e)
        if a <= current_aff:
            break
        if swap_filter and not swap_filter(e):
            continue
        tags = shared_tags(e, profile)
        why = ("shares " + ", ".join(t.name for t in tags[:3])) if tags else "higher Qloo affinity for this profile"
        return Swap(entity=e, qloo_affinity=a, relative_fit=relative_fit(a, best), shared_tags=tags, reason=why)
    return None


async def check_one(client: QlooClient, profile: Profile, cand: Candidate, *,
                    th: Thresholds = DEFAULT, swap_filter: SwapFilter | None = None,
                    _ranked_cache: dict[str, list[EntityRef]] | None = None) -> CheckResult:
    try:
        etype = domain_to_type(cand.domain)
    except ValueError as exc:
        res = Resolution(status=ResolutionStatus.cannot_verify, reason=str(exc))
        return CheckResult(candidate=cand, resolution=res, verdict=Verdict.cannot_verify)
    res = await resolve(client, cand, th)
    if res.status is ResolutionStatus.ambiguous:
        return CheckResult(candidate=cand, resolution=res, verdict=Verdict.needs_confirmation)
    if res.status is ResolutionStatus.cannot_verify:
        return CheckResult(candidate=cand, resolution=res, verdict=Verdict.cannot_verify)
    assert res.entity is not None
    if not profile_signals(profile):
        res.reason = "profile has no confirmed Qloo signals yet"
        return CheckResult(candidate=cand, resolution=res, verdict=Verdict.cannot_verify)

    cache = _ranked_cache if _ranked_cache is not None else {}
    if etype not in cache:
        cache[etype] = await top_for(client, profile, etype, take=10)
    scored = await score_entities(client, profile, etype, [res.entity.id])
    ent = scored.get(res.entity.id)
    if ent is None:
        res.reason = "Qloo returned no affinity for this entity"
        return CheckResult(candidate=cand, resolution=res, verdict=Verdict.cannot_verify)
    res.entity = ent  # now carries Qloo tags/properties
    return assess(cand, res, ent, cache[etype], profile, th=th, swap_filter=swap_filter)


def assess(cand: Candidate, res: Resolution, ent: EntityRef, ranked: list[EntityRef], profile: Profile,
           *, th: Thresholds = DEFAULT, swap_filter: SwapFilter | None = None) -> CheckResult:
    """Pure: verdict, evidence and swap for an entity Qloo has already scored."""
    aff = affinity_of(ent)
    best = max([aff, *(affinity_of(e) for e in ranked)])
    rel = relative_fit(aff, best)
    ev = Evidence(qloo_affinity=aff, best_available_affinity=best, relative_fit=rel,
                  shared_tags=shared_tags(ent, profile))
    verdict = classify(rel, th)
    if ent.id in profile.disliked:
        verdict = Verdict.poor
        ev.notes.append("Hearth feedback: staff recorded this was not enjoyed")
    if swap_filter and not swap_filter(ent):
        ev.notes.append("fails a Hearth care rule (see constraints)")
        if verdict is Verdict.good:
            verdict = Verdict.weak
    swap = None
    if verdict is not Verdict.good:
        swap = pick_swap(ranked, aff, best, profile, {ent.id, *profile.disliked}, swap_filter)
    return CheckResult(candidate=cand, resolution=res, verdict=verdict, evidence=ev, swap=swap)


async def verify(client: QlooClient, profile: Profile, candidates: list[Candidate], *,
                 th: Thresholds = DEFAULT, swap_filter: SwapFilter | None = None) -> VerifyReport:
    cache: dict[str, list[EntityRef]] = {}
    results = [await check_one(client, profile, c, th=th, swap_filter=swap_filter, _ranked_cache=cache)
               for c in candidates]
    counts: dict[str, int] = {}
    for r in results:
        counts[r.verdict.value] = counts.get(r.verdict.value, 0) + 1
    return VerifyReport(profile_name=profile.name, results=results, counts=counts)
