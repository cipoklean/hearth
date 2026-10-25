"""Town -> Qloo point filter, for towns Qloo can't resolve as a named locality."""
from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)
GEOCODE_URL = os.environ.get("HEARTH_GEOCODE_URL", "https://geocoding-api.open-meteo.com/v1/search")
RADIUS_M = 25_000


async def geocode_point(city: str, *, transport: httpx.AsyncBaseTransport | None = None) -> dict | None:
    """Best match for ``city`` (``"Town"`` or ``"Town, Country"``) as Qloo filter params, or None."""
    name, _, hint = (part.strip() for part in city.partition(","))
    if not name:
        return None
    try:
        async with httpx.AsyncClient(timeout=6.0, transport=transport) as http:
            resp = await http.get(GEOCODE_URL, params={"name": name, "count": 10, "language": "en"})
            resp.raise_for_status()
            results = resp.json().get("results") or []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("geocode %r failed: %s", city, exc)
        return None
    if hint:
        h = hint.lower()
        results = [r for r in results if h in " ".join(str(r.get(k, "")) for k in
                   ("country", "country_code", "admin1", "admin2")).lower()] or results
    if not results:
        return None
    best = max(results, key=lambda r: r.get("population") or 0)
    return {"filter.location": f"POINT({best['longitude']} {best['latitude']})",
            "filter.location.radius": RADIUS_M}
