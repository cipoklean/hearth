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
    r = api.get("/api/resolve", params={"name": artist_name, "domain": "artist"})
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    e = r.json()["entity"]
    body = {"name": name, "entities": [{"id": e["id"], "name": e["name"], "type": "artist", "tags": e["tags"]}],
            "needs": list(needs)}
    r = api.post("/api/residents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["resident_id"]


def test_health(api):
    assert api.get("/api/health").json()["mock"] is True


def test_full_flow(api):
    ada = _resident(api, "Ada", "The Marlow Sisters", ["soft_food", "mild_content"])
    bayo = _resident(api, "Bayo", "Teddy Okafor & His Highlife Band")
    cy = _resident(api, "Cy", "Grindcore Unit")

    r = api.post("/api/verify", json={"resident_id": ada, "candidates": [
        {"name": "Dancing on the Pier", "domain": "movie"},
        {"name": "Iron Front", "domain": "movie"}]})
    assert r.status_code == 200, r.text
    res = {x["candidate"]["name"]: x for x in r.json()["results"]}
    assert res["Dancing on the Pier"]["verdict"] == "good"
    assert res["Iron Front"]["verdict"] in {"weak", "poor"} and res["Iron Front"]["swap"]

    plan = api.get(f"/api/residents/{ada}/plan")
    assert plan.status_code == 200 and len(plan.json()["items"]) == 5

    g = api.post("/api/group-pick", json={"resident_ids": [ada, bayo, cy], "domain": "movie"})
    assert g.status_code == 200, g.text
    assert any(l["name"] == "Cy" for l in g.json()["left_out"])

    # feedback: Ada didn't enjoy Dancing on the Pier (not in her profile) -> disliked -> poor
    fb = api.post("/api/feedback", json={"resident_id": ada, "enjoyed": False,
                                     "entity": {"id": "mock-movie-003", "name": "Dancing on the Pier", "type": "movie"}})
    assert fb.status_code == 200 and "mock-movie-003" in fb.json()["disliked"]
    r = api.post("/api/verify", json={"resident_id": ada, "candidates": [{"name": "Dancing on the Pier", "domain": "movie"}]})
    assert r.json()["results"][0]["verdict"] == "poor"
    # enjoyed again -> back as a signal
    fb = api.post("/api/feedback", json={"resident_id": ada, "enjoyed": True,
                                     "entity": {"id": "mock-movie-003", "name": "Dancing on the Pier", "type": "movie"}})
    assert "mock-movie-003" not in fb.json()["disliked"]


def test_venue_facts_change_rules(api):
    ada = _resident(api, "Ada", "The Marlow Sisters", ["wheelchair_access"])
    plan = api.get(f"/api/residents/{ada}/plan").json()
    outing = next(i for i in plan["items"] if i["slot"] == "outing")
    vid = outing["entity"]["id"]
    api.put(f"/api/venues/{vid}/facts", json={"step_free": False})
    plan2 = api.get(f"/api/residents/{ada}/plan").json()
    outing2 = next(i for i in plan2["items"] if i["slot"] == "outing")
    assert outing2["entity"]["id"] != vid


def test_errors(api):
    assert api.get("/api/residents/nope/plan").status_code == 404
    assert api.get("/api/resolve", params={"name": "x", "domain": "music"}).status_code == 422
    assert api.post("/api/verify", json={"candidates": [{"name": "x", "domain": "movie"}]}).status_code == 422
    assert api.post("/api/residents", json={"name": ""}).status_code == 422


def test_delete_resident_removes_everything(api):
    ada = _resident(api, "Ada", "The Marlow Sisters", ["soft_food"])
    api.post("/api/feedback", json={"resident_id": ada, "enjoyed": True,
                                    "entity": {"id": "mock-movie-003", "name": "Dancing on the Pier", "type": "movie"}})
    assert [r["resident_id"] for r in api.get("/api/residents").json()] == [ada]
    assert api.get(f"/api/residents/{ada}/history").json()[0]["name"] == "Dancing on the Pier"
    r = api.delete(f"/api/residents/{ada}")
    assert r.status_code == 204
    assert api.get(f"/api/residents/{ada}").status_code == 404
    assert api.get("/api/residents").json() == []
    store = api.app.state.store
    for table in ("resident_entities", "resident_tags", "feedback"):
        n = store._conn.execute(f"SELECT COUNT(*) FROM {table} WHERE resident_id = ?", (ada,)).fetchone()[0]
        assert n == 0, table
    assert api.delete(f"/api/residents/{ada}").status_code == 404


def test_homes_are_separate(api):
    a = {"X-Hearth-Home": "browser-a"}
    b = {"X-Hearth-Home": "browser-b"}
    r = api.post("/api/residents", headers=a, json={"name": "Ada"})
    rid = r.json()["resident_id"]
    assert len(api.get("/api/residents", headers=a).json()) == 1
    assert api.get("/api/residents", headers=b).json() == []
    assert api.get(f"/api/residents/{rid}", headers=b).status_code == 404
    assert api.delete(f"/api/residents/{rid}", headers=b).status_code == 404
    assert api.delete("/api/home", headers=a).json()["deleted_residents"] == 1


def test_demo_seed_is_idempotent(api):
    h = {"X-Hearth-Home": "demo-1"}
    r = api.post("/api/demo", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 4 and r.json()["home"]["name"] == "Maple House"
    res = api.get("/api/residents", headers=h).json()
    assert [p["name"] for p in res] == ["Rose", "Dorothy", "Earl", "Margaret"]
    assert all(p["entities"] and p["needs"] for p in res)
    assert api.post("/api/demo", headers=h).json()["created"] == 0
    assert len(api.get("/api/residents", headers=h).json()) == 4
    g = api.post("/api/group-pick", headers=h,
                 json={"resident_ids": [p["resident_id"] for p in res], "domain": "movie"})
    assert g.status_code == 200 and g.json()["pick"]


def test_search_and_plan_swap(api):
    s = api.get("/api/search", params={"q": "Harbour Lights", "domain": "movie"}).json()
    assert len(s["results"]) >= 2 and all("display_tags" in x for x in s["results"])
    ada = _resident(api, "Ada", "The Marlow Sisters")
    plan = api.get(f"/api/residents/{ada}/plan").json()
    music = next(i for i in plan["items"] if i["slot"] == "music_session")
    meal = next(i for i in plan["items"] if i["slot"] == "meal_theme" and i["cuisine"])
    plan2 = api.get(f"/api/residents/{ada}/plan",
                    params={"skip": music["entity"]["id"], "skip_cuisine": meal["cuisine"]}).json()
    music2 = next(i for i in plan2["items"] if i["slot"] == "music_session")
    assert music2.get("entity") is None or music2["entity"]["id"] != music["entity"]["id"]
    assert meal["cuisine"] not in [i["cuisine"] for i in plan2["items"] if i["slot"] == "meal_theme"]


def test_serves_web_app(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Hearth</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    app = create_app(client=QlooClient(mock=True), db_path=str(tmp_path / "t.db"), web_dist=dist)
    with TestClient(app) as c:
        assert "Hearth" in c.get("/").text
        assert "Hearth" in c.get("/residents/abc").text  # client-side route
        assert c.get("/assets/app.js").status_code == 200
        assert c.get("/api/health").json()["ok"] is True
        assert c.get("/api/nope").status_code == 404
