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


def test_plan_survives_unplaceable_town(tmp_path):
    from fastapi.testclient import TestClient
    from hearth.api import create_app
    from hearth.qloo import QlooClient
    app = create_app(client=QlooClient(mock=True), db_path=str(tmp_path / "t.db"), rate_limiter=False)
    h = {"X-Hearth-Home": "h-" + "c" * 32}
    with TestClient(app) as c:
        c.post("/api/demo", headers=h)
        c.put("/api/home", json={"name": "T", "city": "Nowhere"}, headers=h)
        app.state.locations["nowhere"] = None  # as if Qloo and the geocoder both failed
        rid = c.get("/api/residents", headers=h).json()[0]["resident_id"]
        r = c.get(f"/api/residents/{rid}/plan", headers=h)
        assert r.status_code == 200
        assert "couldn't find Nowhere" in r.json()["notes"][0]
