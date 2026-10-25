import asyncio

import httpx

from hearth.geo import geocode_point


def _transport(results):
    return httpx.MockTransport(lambda req: httpx.Response(200, json={"results": results}))


def test_geocode_picks_country_hint_then_population():
    res = [{"name": "Awka", "country": "Elsewhere", "latitude": 1, "longitude": 2, "population": 9e6},
           {"name": "Awka", "country": "Nigeria", "country_code": "NG", "latitude": 6.2, "longitude": 7.0,
            "population": 300000}]
    out = asyncio.run(geocode_point("Awka, Nigeria", transport=_transport(res)))
    assert out == {"filter.location": "POINT(7.0 6.2)", "filter.location.radius": 12000}


def test_geocode_unknown_town_is_none():
    assert asyncio.run(geocode_point("Nowhere", transport=_transport([]))) is None


def test_geocode_network_error_is_none():
    def boom(req):
        raise httpx.ConnectError("down")
    assert asyncio.run(geocode_point("Enugu", transport=httpx.MockTransport(boom))) is None


def test_geocode_city_gets_wider_radius():
    res = [{"name": "Lagos", "country": "Nigeria", "latitude": 6.45, "longitude": 3.39, "population": 9e6}]
    out = asyncio.run(geocode_point("Lagos", transport=_transport(res)))
    assert out["filter.location.radius"] == 25000
