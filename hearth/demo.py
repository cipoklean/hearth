"""Sample care home ("Maple House") for the first-time experience.

Residents are defined by *names only*. Their favourites are resolved against
Qloo at seed time (live responses go through the private, gitignored disk
cache), so no Qloo IDs or response data live in the repository. In mock mode
the same four people get stand-in favourites from the synthetic catalogue.

The four live personas mirror the calibration set in plan/calibration.md.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .models import EntityRef, Need
from .qloo import QlooClient
from .verifier import ResolutionStatus, domain_to_type, match_candidates

DEMO_HOME = "Maple House"
DEMO_CITY = "London"


@dataclass(frozen=True)
class DemoResident:
    name: str
    blurb: str
    favourites: tuple[tuple[str, str, int | None], ...]  # (domain, name, release year or None)
    needs: tuple[Need, ...]


LIVE: tuple[DemoResident, ...] = (
    DemoResident("Rose", "Swing and classic Hollywood",
                 (("artist", "Frank Sinatra", None), ("artist", "Ella Fitzgerald", None),
                  ("artist", "Glenn Miller", None), ("movie", "Casablanca", None),
                  ("movie", "Singin' in the Rain", None), ("movie", "Roman Holiday", 1953)),
                 (Need.soft_food, Need.mild_content)),
    DemoResident("Dorothy", "Motown and soul",
                 (("artist", "The Supremes", None), ("artist", "Marvin Gaye", None),
                  ("artist", "The Temptations", None), ("movie", "Sister Act", None)),
                 (Need.low_sugar, Need.short_duration)),
    DemoResident("Earl", "Country and westerns",
                 (("artist", "Johnny Cash", None), ("artist", "Patsy Cline", None),
                  ("artist", "Hank Williams", None), ("movie", "The Searchers", 1956),
                  ("movie", "High Noon", 1952)),
                 (Need.wheelchair_access, Need.low_salt)),
    DemoResident("Margaret", "Classical and opera",
                 (("artist", "Luciano Pavarotti", None), ("artist", "Maria Callas", None),
                  ("artist", "Ludwig van Beethoven", None), ("movie", "Amadeus", 1984),
                  ("movie", "A Room with a View", 1986)),
                 (Need.hearing_support, Need.vegetarian)),
)

# Offline stand-ins: names from hearth/qloo/fixtures/synthetic_catalog.json (all invented).
MOCK: tuple[DemoResident, ...] = (
    DemoResident("Rose", "Swing and classic musicals",
                 (("artist", "The Marlow Sisters", None), ("artist", "The Jivetones", None),
                  ("movie", "Dancing on the Pier", None)),
                 (Need.soft_food, Need.mild_content)),
    DemoResident("Dorothy", "Soul, gospel and choirs",
                 (("artist", "Ruth Adair", None), ("artist", "Mahalia Grace Choir", None),
                  ("movie", "The Village Choir", None)),
                 (Need.low_sugar, Need.short_duration)),
    DemoResident("Earl", "Country and westerns",
                 (("artist", "Buck Hollis", None), ("movie", "Dust Road West", None)),
                 (Need.wheelchair_access, Need.low_salt)),
    DemoResident("Margaret", "Classical and romance",
                 (("artist", "The Silverline Orchestra", None), ("movie", "Harbour Lights", 1954)),
                 (Need.hearing_support, Need.vegetarian)),
)


def personas(mock: bool) -> tuple[DemoResident, ...]:
    return MOCK if mock else LIVE


async def resolve_favourite(client: QlooClient, domain: str, name: str, year: int | None) -> EntityRef | None:
    etype = domain_to_type(domain)
    results = [r for r in await client.search(name, types=[etype], take=5) if r.type == etype]
    if year is not None:
        dated = [r for r in results if r.name.lower() == name.lower()
                 and r.properties.get("release_year") == year]
        if dated:
            return max(dated, key=lambda r: float(r.properties.get("popularity") or 0))
    res = match_candidates(name, results)
    return res.entity if res.status is ResolutionStatus.resolved else None


async def resolve_demo(client: QlooClient) -> list[tuple[DemoResident, list[EntityRef]]]:
    """Resolve every demo favourite (in parallel). Unresolvable names are skipped."""
    out = []
    for p in personas(client.mock):
        ents = await asyncio.gather(*(resolve_favourite(client, d, n, y) for d, n, y in p.favourites))
        out.append((p, [e for e in ents if e is not None]))
    return out
