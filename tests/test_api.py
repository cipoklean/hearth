import pytest
from fastapi.testclient import TestClient

from hearth.api import create_app
from hearth.qloo import QlooClient


@pytest.fixture
def api(tmp_path):
    app = create_app(client=QlooClient(mock=True), db_path=str(tmp_path / "t.db"))
    with TestClient(app) as c:
        yield c


def _resident(api, name, artist_name, needs=()):
    r = api.get("/resolve", params={"name": artist_name, "domain": "artist"})
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    e = r.json()["entity"]
    body = {"name": name, "entities": [{"id": e["id"], "name": e["name"], "type": "artist", "tags": e["tags"]}],
            "needs": list(needs)}
    r = api.post("/residents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["resident_id"]


def test_health(api):
    assert api.get("/health").json()["mock"] is True


def test_full_flow(api):
    ada = _resident(api, "Ada", "The Marlow Sisters", ["soft_food", "mild_content"])
    bayo = _resident(api, "Bayo", "Teddy Okafor & His Highlife Band")
    cy = _resident(api, "Cy", "Grindcore Unit")

    r = api.post("/verify", json={"resident_id": ada, "candidates": [
        {"name": "Dancing on the Pier", "domain": "movie"},
        {"name": "Iron Front", "domain": "movie"}]})
    assert r.status_code == 200, r.text
    res = {x["candidate"]["name"]: x for x in r.json()["results"]}
    assert res["Dancing on the Pier"]["verdict"] == "good"
    assert res["Iron Front"]["verdict"] in {"weak", "poor"} and res["Iron Front"]["swap"]

    plan = api.get(f"/residents/{ada}/plan")
    assert plan.status_code == 200 and len(plan.json()["items"]) == 5

    g = api.post("/group-pick", json={"resident_ids": [ada, bayo, cy], "domain": "movie"})
    assert g.status_code == 200, g.text
    assert any(l["name"] == "Cy" for l in g.json()["left_out"])

    # feedback: Ada didn't enjoy Dancing on the Pier (not in her profile) -> disliked -> poor
    fb = api.post("/feedback", json={"resident_id": ada, "enjoyed": False,
                                     "entity": {"id": "mock-movie-003", "name": "Dancing on the Pier", "type": "movie"}})
    assert fb.status_code == 200 and "mock-movie-003" in fb.json()["disliked"]
    r = api.post("/verify", json={"resident_id": ada, "candidates": [{"name": "Dancing on the Pier", "domain": "movie"}]})
    assert r.json()["results"][0]["verdict"] == "poor"
    # enjoyed again -> back as a signal
    fb = api.post("/feedback", json={"resident_id": ada, "enjoyed": True,
                                     "entity": {"id": "mock-movie-003", "name": "Dancing on the Pier", "type": "movie"}})
    assert "mock-movie-003" not in fb.json()["disliked"]


def test_venue_facts_change_rules(api):
    ada = _resident(api, "Ada", "The Marlow Sisters", ["wheelchair_access"])
    plan = api.get(f"/residents/{ada}/plan").json()
    outing = next(i for i in plan["items"] if i["slot"] == "outing")
    vid = outing["entity"]["id"]
    api.put(f"/venues/{vid}/facts", json={"step_free": False})
    plan2 = api.get(f"/residents/{ada}/plan").json()
    outing2 = next(i for i in plan2["items"] if i["slot"] == "outing")
    assert outing2["entity"]["id"] != vid


def test_errors(api):
    assert api.get("/residents/nope/plan").status_code == 404
    assert api.get("/resolve", params={"name": "x", "domain": "music"}).status_code == 422
    assert api.post("/verify", json={"candidates": [{"name": "x", "domain": "movie"}]}).status_code == 422
    assert api.post("/residents", json={"name": ""}).status_code == 422
