#!/usr/bin/env python
"""Live smoke test: run Hearth's verifier for four older-adult personas against the real Qloo API.

    QLOO_API_KEY=... python scripts/live_smoke.py [--persona swing] [--no-place]

Personas are defined by *names only*; favourites and picks are resolved live
(responses are cached privately under .cache/qloo, which is gitignored).
Nothing returned by Qloo is written into the repository.

"expect" is a human prior for checking the verifier, not ground truth:
good = clear fit, poor = clear mismatch, weak = close call,
confirm = ambiguous name, cannot = no such entity.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field

from hearth.models import EntityRef, Profile
from hearth.qloo import QlooClient
from hearth.verifier import Candidate, ResolutionStatus, Verdict, match_candidates, verify
from hearth.verifier.core import domain_to_type


@dataclass
class Persona:
    key: str
    label: str
    favourites: list[tuple[str, str, int | None]]          # (domain, name, release year or None)
    picks: list[tuple[str, str, str]]                       # (domain, name, expect)
    place_city: str | None = None
    notes: list[str] = field(default_factory=list)


PERSONAS = [
    Persona("swing", "1950s jazz/swing + classic Hollywood",
            [("artist", "Frank Sinatra", None), ("artist", "Ella Fitzgerald", None), ("artist", "Glenn Miller", None),
             ("movie", "Casablanca", None), ("movie", "Singin' in the Rain", None), ("movie", "Roman Holiday", 1953)],
            [("artist", "Nat King Cole", "good"), ("artist", "Bing Crosby", "good"), ("artist", "Doris Day", "good"),
             ("artist", "Elvis Presley", "weak"), ("artist", "Michael Bublé", "weak"),
             ("artist", "Chief Keef", "poor"), ("artist", "Pop Smoke", "poor"), ("artist", "Slipknot", "poor"),
             ("movie", "An Affair to Remember", "good"), ("movie", "The Philadelphia Story", "good"),
             ("movie", "Mamma Mia!", "weak"), ("movie", "Dreamgirls", "weak"),
             ("movie", "The Texas Chain Saw Massacre", "poor"), ("movie", "Saw", "poor"), ("movie", "Hostel", "poor"),
             ("movie", "Halloween", "confirm"), ("movie", "Little Women", "confirm"),
             ("artist", "Zzqx Nonexistent Orchestra", "cannot"),
             ("place", "Royal Albert Hall", "good"), ("place", "Ronnie Scott's", "good"),
             ("place", "fabric London", "poor")],
            place_city="London"),
    Persona("motown", "Motown / soul",
            [("artist", "The Supremes", None), ("artist", "Marvin Gaye", None), ("artist", "The Temptations", None),
             ("movie", "Sister Act", None)],
            [("artist", "Aretha Franklin", "good"), ("artist", "Stevie Wonder", "good"), ("artist", "The Four Tops", "good"),
             ("artist", "Whitney Houston", "weak"), ("artist", "Elvis Presley", "weak"),
             ("artist", "Slipknot", "poor"), ("artist", "Cannibal Corpse", "poor"), ("artist", "Chief Keef", "poor"),
             ("movie", "Dreamgirls", "good"), ("movie", "Ray", "good"), ("movie", "Mamma Mia!", "weak"),
             ("movie", "Saw", "poor"), ("movie", "Hostel", "poor"), ("movie", "The Texas Chain Saw Massacre", "poor")]),
    Persona("country", "Country / western",
            [("artist", "Johnny Cash", None), ("artist", "Patsy Cline", None), ("artist", "Hank Williams", None),
             ("movie", "The Searchers", 1956), ("movie", "High Noon", 1952)],
            [("artist", "Willie Nelson", "good"), ("artist", "Dolly Parton", "good"), ("artist", "Merle Haggard", "good"),
             ("artist", "Glen Campbell", "good"), ("artist", "Elvis Presley", "weak"), ("artist", "Taylor Swift", "weak"),
             ("artist", "Pop Smoke", "poor"), ("artist", "Skrillex", "poor"), ("artist", "Cannibal Corpse", "poor"),
             ("movie", "Shane", "good"), ("movie", "Rio Bravo", "good"), ("movie", "Walk the Line", "good"),
             ("movie", "True Grit", "confirm"), ("movie", "The Sound of Music", "weak"),
             ("movie", "Saw", "poor"), ("movie", "Hostel", "poor")]),
    Persona("classical", "Classical / opera",
            [("artist", "Luciano Pavarotti", None), ("artist", "Maria Callas", None),
             ("artist", "Ludwig van Beethoven", None), ("movie", "Amadeus", 1984), ("movie", "A Room with a View", 1986)],
            [("artist", "Plácido Domingo", "good"), ("artist", "Andrea Bocelli", "good"),
             ("artist", "Wolfgang Amadeus Mozart", "good"), ("artist", "André Rieu", "weak"), ("artist", "Enya", "weak"),
             ("artist", "Chief Keef", "poor"), ("artist", "Slipknot", "poor"), ("artist", "Pop Smoke", "poor"),
             ("movie", "The Red Shoes", "good"), ("movie", "The Sound of Music", "good"), ("movie", "Mamma Mia!", "weak"),
             ("movie", "Saw", "poor"), ("movie", "Hostel", "poor"), ("movie", "Fast & Furious 6", "poor"),
             ("place", "Wigmore Hall", "good"), ("place", "Royal Albert Hall", "good"),
             ("place", "Ministry of Sound", "poor"), ("place", "fabric London", "poor")],
            place_city="London"),
]

EXPECT_TO_VERDICT = {"good": Verdict.good, "weak": Verdict.weak, "poor": Verdict.poor,
                     "confirm": Verdict.needs_confirmation, "cannot": Verdict.cannot_verify}


async def resolve_favourite(client: QlooClient, domain: str, name: str, year: int | None) -> EntityRef | None:
    etype = domain_to_type(domain)
    results = [r for r in await client.search(name, types=[etype], take=5) if r.type == etype]
    if year is not None:
        dated = [r for r in results if r.name.lower() == name.lower()
                 and r.properties.get("release_year") == year]
        if dated:
            return max(dated, key=lambda r: float(r.properties.get("popularity") or 0))
    res = match_candidates(name, results)
    if res.status is ResolutionStatus.resolved:
        return res.entity
    return None


async def run(personas: list[Persona], with_place: bool) -> int:
    rows: list[tuple] = []
    unresolved: list[str] = []
    async with QlooClient() as client:
        for p in personas:
            favs = []
            for d, n, y in p.favourites:
                e = await resolve_favourite(client, d, n, y)
                if e is None:
                    unresolved.append(f"{p.key}: favourite {n!r} did not resolve")
                else:
                    favs.append(e)
            profile = Profile(resident_id=p.key, name=p.label, entities=favs)
            picks = [x for x in p.picks if with_place or x[0] != "place"]
            extra = {"place": {"filter.location.query": p.place_city}} if p.place_city else None
            rep = await verify(client, profile, [Candidate(name=n, domain=d) for d, n, _ in picks],
                               ranked_extra=extra)
            for (d, n, expect), r in zip(picks, rep.results):
                ev = r.evidence
                ok = r.verdict is EXPECT_TO_VERDICT[expect]
                rows.append((p.key, d, n, expect, r.verdict.value,
                             f"{ev.relative_fit:.3f}" if ev.relative_fit is not None else "-",
                             f"{ev.qloo_affinity:.3f}" if ev.qloo_affinity is not None else "-",
                             (r.swap.entity.name if r.swap else ""), "ok" if ok else "MISS"))
        calls = client.request_count
    widths = [9, 6, 28, 7, 18, 6, 6, 30, 4]
    head = ("persona", "domain", "pick", "expect", "verdict", "rel", "aff", "swap", "")
    print("  ".join(h.ljust(w) for h, w in zip(head, widths)))
    for row in rows:
        print("  ".join(str(c)[:w].ljust(w) for c, w in zip(row, widths)))
    hits = sum(r[-1] == "ok" for r in rows)
    print(f"\n{hits}/{len(rows)} verdicts match the human prior; network calls this run: {calls}")
    for u in unresolved:
        print("WARN", u)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", choices=[p.key for p in PERSONAS])
    ap.add_argument("--no-place", action="store_true", help="skip place picks (provisional thresholds)")
    a = ap.parse_args()
    ps = [p for p in PERSONAS if a.persona in (None, p.key)]
    return asyncio.run(run(ps, with_place=not a.no_place))


if __name__ == "__main__":
    sys.exit(main())
