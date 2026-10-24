"""The taste checker.

verify(profile, candidates):
  1. resolve each free-text name to a Qloo entity (/search); ambiguous names
     come back for confirmation, no match -> cannot_verify
  2. score fit via /v2/insights (profile signals, filter.results.entities)
  3. attach evidence: Qloo affinity, best available affinity, shared tags
  4. verdict good / weak / poor from *relative* fit (affinity vs the best
     Qloo offers this profile in that domain), with per-type absolute floors.
     Thresholds were calibrated against the live API on 2026-10-24 with four
     older-adult personas; see plan/calibration.md in the project folder.
  5. propose a better-fitting swap from Qloo's live ranked list (insights)

Pure helpers are separated from the async I/O so they can be unit-tested.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping

from ..models import EntityRef, Profile, Tag
from ..qloo import QlooClient
from ..qloo.params import DOMAINS, normalize_type
from .models import (Candidate, CheckResult, Evidence, Resolution, ResolutionStatus, SignalContribution,
                     Swap, Verdict, VerifyReport)

SwapFilter = Callable[[EntityRef], bool]


@dataclass(frozen=True)
class TypeThresholds:
    good: float                    # relative fit needed for "good"
    weak: float                    # relative fit needed for "weak"
    good_abs: float | None = None  # absolute Qloo affinity also needed for "good"
    weak_abs: float | None = None  # below this absolute affinity -> "poor" whatever the relative fit
    status: str = "uncalibrated"   # calibrated | provisional | uncalibrated


# Live calibration 2026-10-24 (4 personas, 2 domains, 65 scored picks; numbers in plan/calibration.md):
#   artist rel: fits 0.946-1.00, close calls 0.79-0.94, mismatches 0.72-0.79
#   movie  rel: fits 0.915-0.99, close calls 0.865-0.94, mismatches 0.67-0.815
#   absolute:   fits >= 0.845, mismatches <= 0.766
#   place  rel: concert halls 0.95-0.98, jazz club 0.94, nightclubs/attractions 0.86-0.92 (London, 2 personas)
_CALIBRATED = TypeThresholds(good=0.94, weak=0.84, good_abs=0.85, weak_abs=0.78, status="calibrated")
_PER_TYPE: dict[str, TypeThresholds] = {
    "urn:entity:artist": _CALIBRATED,
    "urn:entity:movie": _CALIBRATED,
    # Places score in a much narrower band and lean on landmark popularity: relative only, provisional.
    "urn:entity:place": TypeThresholds(good=0.95, weak=0.90, status="provisional"),
}


@dataclass(frozen=True)
class Thresholds:
    good: float = 0.94   # default relative-fit thresholds for types without their own entry
    weak: float = 0.84
    per_type: Mapping[str, TypeThresholds] = field(default_factory=lambda: dict(_PER_TYPE))
    exact_unique_ratio: float = 0.90
    fuzzy_min_ratio: float = 0.60
    # Several entities with the exact name: resolve to the most popular one when it leads every
    # other exact match by this much (live: many titles have popularity-0 duplicate stubs).
    popularity_lead: float = 0.30

    def for_type(self, etype: str | None) -> TypeThresholds:
        if etype and etype in self.per_type:
            return self.per_type[etype]
        return TypeThresholds(good=self.good, weak=self.weak)


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
        by_pop = sorted(exact, key=lambda r: -_popularity(r))
        lead = _popularity(by_pop[0]) - _popularity(by_pop[1])
        if lead >= th.popularity_lead:
            return Resolution(status=ResolutionStatus.resolved, entity=by_pop[0],
                              options=by_pop[1:],
                              reason=f"{len(exact)} entities share this name; chose the far better-known one "
                                     f"({_label(by_pop[0])}); confirm if another was meant")
        return Resolution(status=ResolutionStatus.ambiguous, options=by_pop,
                          reason=f"{len(exact)} entities share this name; confirm which one")
    ratios = sorted(((difflib.SequenceMatcher(None, n, _norm(r.name)).ratio(), r) for r in results),
                    key=lambda x: -x[0])
    top, top_r = ratios[0][0], ratios[0][1]
    second = ratios[1][0] if len(ratios) > 1 else 0.0
    if top >= th.exact_unique_ratio and top - second >= 0.1:
        return Resolution(status=ResolutionStatus.resolved, entity=top_r,
                          reason=f"close name match ({top:.2f})")
    # A shared generic word ("Orchestra", "Band") inflates the character ratio, so a fuzzy option
    # also needs real word overlap unless the strings are very close (live: a made-up
    # "... Orchestra" matched "Manchester Orchestra" at 0.65).
    close = [r for s, r in ratios if s >= th.fuzzy_min_ratio and (s >= 0.8 or _token_jaccard(n, _norm(r.name)) >= 0.5)]
    if close:
        return Resolution(status=ResolutionStatus.ambiguous, options=close,
                          reason="no exact name match; confirm the intended entity")
    return Resolution(status=ResolutionStatus.cannot_verify, reason="no close Qloo name match")


def _token_jaccard(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def _popularity(e: EntityRef) -> float:
    try:
        return float(e.properties.get("popularity") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _label(e: EntityRef) -> str:
    year = e.properties.get("release_year") or e.properties.get("year")
    return f"{e.name}, {year}" if year else e.name


# Display order for evidence tags: genre/style words first, audience adjectives ("Loyal",
# "Diverse") and noisy keyword tags last. Matched on the tag id's category segment.
_TAG_RANK = ("genre", "subgenre", "style", "influence", "category", "music", "theme", "plot",
             "setting", "ambience", "activity_type", "instrument", "interests", "archetype", "character",
             "artist", "characteristic", "keyword", "audience")
_TAG_DROP = ("obscurity", "time_of_day_fit")


def _tag_rank(tag_id: str) -> int:
    parts = tag_id.split(":")
    cat = parts[2] if len(parts) > 2 else ""
    return _TAG_RANK.index(cat) if cat in _TAG_RANK else len(_TAG_RANK)


def shared_tags(entity: EntityRef, profile: Profile) -> list[Tag]:
    """Tags this entity shares with the person's favourites, genre/style tags first."""
    known = profile.known_tags()
    out, seen = [], set()
    for t in entity.tags:
        if t.id not in known or any(f":{d}:" in t.id for d in _TAG_DROP):
            continue
        name = t.name or known.get(t.id, t.id)
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(Tag(id=t.id, name=name))
    out.sort(key=lambda t: _tag_rank(t.id))  # stable: keeps Qloo's order within a rank
    return out


def relative_fit(affinity: float, best: float) -> float:
    if best <= 0:
        return 0.0
    return round(min(1.0, affinity / best), 4)


def classify(rel: float, th: Thresholds = DEFAULT, *, affinity: float | None = None,
             etype: str | None = None) -> Verdict:
    """Relative fit -> verdict, using the thresholds for ``etype`` and its absolute floors."""
    t = th.for_type(etype)
    if affinity is not None and t.weak_abs is not None and affinity < t.weak_abs:
        return Verdict.poor
    if rel >= t.good and (affinity is None or t.good_abs is None or affinity >= t.good_abs):
        return Verdict.good
    if rel >= t.weak:
        return Verdict.weak
    return Verdict.poor


def signal_contributions(e: EntityRef, profile: Profile) -> list[SignalContribution]:
    """Qloo explainability: share of this entity's score owed to each profile favourite."""
    ex = e.properties.get("explainability") or {}
    names = {x.id: x.name for x in profile.entities}
    out = [SignalContribution(entity_id=k, name=names.get(k, k), share=round(float(v), 4))
           for k, v in ex.items()]
    out.sort(key=lambda c: -c.share)
    return out


def leading_favourite(contribs: list[SignalContribution], lift: float = 1.15) -> SignalContribution | None:
    """The favourite that clearly drives the score (share >= lift x an even split), if any.

    Live: for clear mismatches the shares are near-even, so this returns None for them.
    """
    if len(contribs) < 2:  # one favourite always gets 100%: says nothing
        return None
    top = contribs[0]
    return top if top.share >= lift / len(contribs) else None


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
    out: dict[str, EntityRef] = {}
    for i in range(0, len(ids), 50):  # take is capped at 50
        chunk = ids[i:i + 50]
        ents = await client.insights({"filter.type": etype, **sig, "filter.results.entities": chunk,
                                      "take": len(chunk), "feature.explainability": True})
        out.update({e.id: e for e in ents})
    return out


async def top_for(client: QlooClient, profile: Profile, etype: str, *, take: int = 10,
                  exclude: Iterable[str] = (), extra: dict | None = None) -> list[EntityRef]:
    sig = profile_signals(profile)
    if not sig:
        return []
    p: dict = {"filter.type": etype, **sig, "take": take, "feature.explainability": True}
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
        lead = leading_favourite(signal_contributions(e, profile))
        parts = []
        if lead:
            parts.append(f"Qloo links it most to {lead.name}")
        if tags:
            parts.append("shares " + ", ".join(t.name for t in tags[:3]))
        why = "; ".join(parts) or "higher Qloo affinity for this profile"
        return Swap(entity=e, qloo_affinity=a, relative_fit=relative_fit(a, best), shared_tags=tags, reason=why)
    return None


def _preflight(profile: Profile, cand: Candidate) -> CheckResult | str:
    """Domain check; returns the Qloo type or an early cannot_verify result."""
    try:
        return domain_to_type(cand.domain)
    except ValueError as exc:
        res = Resolution(status=ResolutionStatus.cannot_verify, reason=str(exc))
        return CheckResult(candidate=cand, resolution=res, verdict=Verdict.cannot_verify)


def _unresolved(cand: Candidate, res: Resolution, profile: Profile) -> CheckResult | None:
    if res.status is ResolutionStatus.ambiguous:
        return CheckResult(candidate=cand, resolution=res, verdict=Verdict.needs_confirmation)
    if res.status is ResolutionStatus.cannot_verify:
        return CheckResult(candidate=cand, resolution=res, verdict=Verdict.cannot_verify)
    if not profile_signals(profile):
        res.reason = "profile has no confirmed Qloo signals yet"
        return CheckResult(candidate=cand, resolution=res, verdict=Verdict.cannot_verify)
    if res.entity is not None and res.entity.id in profile.signal_entity_ids():
        # Live API: signal entities are never returned as results, even via filter.results.entities.
        ev = Evidence(notes=["already one of their confirmed favourites (Qloo does not score a "
                             "favourite against itself)"])
        return CheckResult(candidate=cand, resolution=res, verdict=Verdict.good, evidence=ev)
    return None


def _scored(cand: Candidate, res: Resolution, ent: EntityRef | None, ranked: list[EntityRef], profile: Profile,
            th: Thresholds, swap_filter: SwapFilter | None) -> CheckResult:
    if ent is None:
        res.reason = "Qloo returned no affinity for this entity"
        return CheckResult(candidate=cand, resolution=res, verdict=Verdict.cannot_verify)
    if res.entity is not None and res.entity.properties.get("popularity") is not None:
        ent.properties.setdefault("popularity", res.entity.properties["popularity"])
    res.entity = ent  # now carries Qloo tags/properties
    return assess(cand, res, ent, ranked, profile, th=th, swap_filter=swap_filter)


async def check_one(client: QlooClient, profile: Profile, cand: Candidate, *,
                    th: Thresholds = DEFAULT, swap_filter: SwapFilter | None = None,
                    _ranked_cache: dict[str, list[EntityRef]] | None = None) -> CheckResult:
    pre = _preflight(profile, cand)
    if isinstance(pre, CheckResult):
        return pre
    etype = pre
    res = await resolve(client, cand, th)
    if (early := _unresolved(cand, res, profile)) is not None:
        return early
    assert res.entity is not None
    cache = _ranked_cache if _ranked_cache is not None else {}
    if etype not in cache:
        cache[etype] = await top_for(client, profile, etype, take=10)
    scored = await score_entities(client, profile, etype, [res.entity.id])
    return _scored(cand, res, scored.get(res.entity.id), cache[etype], profile, th, swap_filter)


def assess(cand: Candidate, res: Resolution, ent: EntityRef, ranked: list[EntityRef], profile: Profile,
           *, th: Thresholds = DEFAULT, swap_filter: SwapFilter | None = None) -> CheckResult:
    """Pure: verdict, evidence and swap for an entity Qloo has already scored."""
    aff = affinity_of(ent)
    best = max([aff, *(affinity_of(e) for e in ranked)])
    rel = relative_fit(aff, best)
    t = th.for_type(ent.type)
    contribs = signal_contributions(ent, profile)
    ev = Evidence(qloo_affinity=aff, best_available_affinity=best, relative_fit=rel,
                  shared_tags=shared_tags(ent, profile), signal_contributions=contribs,
                  threshold_status=t.status)
    verdict = classify(rel, th, affinity=aff, etype=ent.type)
    if t.status != "calibrated":
        ev.notes.append(f"verdict thresholds for {ent.type.rsplit(':', 1)[-1]} are {t.status}; treat as a hint")
    if verdict is not Verdict.poor and (lead := leading_favourite(contribs)):
        ev.notes.append(f"Qloo links this most to {lead.name} ({lead.share:.0%} of the score)")
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
                 th: Thresholds = DEFAULT, swap_filter: SwapFilter | None = None,
                 ranked_take: int = 20, ranked_extra: Mapping[str, dict] | None = None) -> VerifyReport:
    """Resolve every candidate, then score per domain in batch: one ranked-list call and one
    filter.results.entities call per domain, however many candidates there are.

    ``ranked_extra`` adds per-domain filters to the ranked list that sets "best available" and the
    swaps, e.g. {"place": {"filter.location.query": "London"}} so outings are compared locally.
    """
    extras = {domain_to_type(k): v for k, v in (ranked_extra or {}).items()}
    results: list[CheckResult | None] = [None] * len(candidates)
    pending: dict[str, list[tuple[int, Resolution]]] = {}
    for i, cand in enumerate(candidates):
        pre = _preflight(profile, cand)
        if isinstance(pre, CheckResult):
            results[i] = pre
            continue
        res = await resolve(client, cand, th)
        if (early := _unresolved(cand, res, profile)) is not None:
            results[i] = early
            continue
        pending.setdefault(pre, []).append((i, res))
    for etype, items in pending.items():
        ranked = await top_for(client, profile, etype, take=ranked_take, extra=extras.get(etype))
        scored = await score_entities(client, profile, etype, [r.entity.id for _, r in items if r.entity])
        for i, res in items:
            assert res.entity is not None
            results[i] = _scored(candidates[i], res, scored.get(res.entity.id), ranked, profile, th, swap_filter)
    done = [r for r in results if r is not None]
    counts: dict[str, int] = {}
    for r in done:
        counts[r.verdict.value] = counts.get(r.verdict.value, 0) + 1
    return VerifyReport(profile_name=profile.name, results=done, counts=counts)
