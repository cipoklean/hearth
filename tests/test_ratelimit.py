"""Public-demo protection: per-IP rate limits and a resident cap per home."""
import pytest
from fastapi.testclient import TestClient

from hearth.api import create_app
from hearth.qloo import QlooClient
from hearth.ratelimit import Limit, RateLimiter, buckets_for


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_limit_parse():
    assert Limit.parse("30/60") == Limit(30, 60.0)
    for bad in ("", "30", "0/60", "a/b", "5/0"):
        with pytest.raises(ValueError):
            Limit.parse(bad)


def test_buckets():
    assert buckets_for("GET", "/api/health") == []
    assert buckets_for("GET", "/") == [] and buckets_for("GET", "/assets/x.js") == []
    assert buckets_for("GET", "/api/search") == ["api", "qloo"]
    assert buckets_for("GET", "/api/residents/abc/plan") == ["api", "qloo"]
    assert buckets_for("POST", "/api/residents") == ["api", "create"]
    assert buckets_for("POST", "/api/demo") == ["api", "qloo", "create"]
    assert buckets_for("PUT", "/api/home") == ["api"]


def test_sliding_window_per_ip():
    clock = Clock()
    rl = RateLimiter({"api": Limit(100, 60), "qloo": Limit(2, 60)}, clock=clock)
    assert rl.check("1.1.1.1", ["api", "qloo"])[0]
    assert rl.check("1.1.1.1", ["api", "qloo"])[0]
    ok, retry, bucket = rl.check("1.1.1.1", ["api", "qloo"])
    assert not ok and bucket == "qloo" and 1 <= retry <= 60
    assert rl.check("2.2.2.2", ["api", "qloo"])[0]       # other visitors unaffected
    assert rl.check("1.1.1.1", ["api"])[0]               # non-Qloo routes still fine
    clock.t += 61
    assert rl.check("1.1.1.1", ["api", "qloo"])[0]       # window has passed


def test_from_env():
    assert RateLimiter.from_env({"HEARTH_RATE_LIMIT": "0"}) is None
    rl = RateLimiter.from_env({"HEARTH_RATE_QLOO": "5/10"})
    assert rl.limits["qloo"] == Limit(5, 10.0) and rl.limits["api"] == Limit(240, 60.0)


def test_prune_bounds_memory():
    clock = Clock()
    rl = RateLimiter({"api": Limit(5, 10)}, clock=clock, max_keys=10)
    for i in range(50):
        rl.check(f"10.0.0.{i}", ["api"])
    clock.t += 11
    rl.check("9.9.9.9", ["api"])
    assert len(rl._hits) <= 11


def _app(tmp_path, **kw):
    return create_app(client=QlooClient(mock=True), db_path=str(tmp_path / "t.db"), **kw)


def test_middleware_returns_429_with_retry_after(tmp_path):
    rl = RateLimiter({"api": Limit(100, 60), "qloo": Limit(3, 60), "create": Limit(10, 3600)})
    with TestClient(_app(tmp_path, rate_limiter=rl)) as c:
        for _ in range(3):
            assert c.get("/api/search", params={"q": "Marlow", "domain": "artist"}).status_code == 200
        r = c.get("/api/search", params={"q": "Marlow", "domain": "artist"})
        assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
        assert "rate limited" in r.json()["detail"]
        assert c.get("/api/health").status_code == 200   # never limited
        assert c.get("/api/home").status_code == 200     # general bucket still has room


def test_resident_cap_per_home(tmp_path):
    with TestClient(_app(tmp_path, rate_limiter=False, max_residents=2)) as c:
        body = {"name": "A", "entities": [], "needs": []}
        h = {"X-Hearth-Home": "home-one"}
        assert c.post("/api/residents", json=body, headers=h).status_code == 201
        assert c.post("/api/residents", json=body, headers=h).status_code == 201
        r = c.post("/api/residents", json=body, headers=h)
        assert r.status_code == 409 and "limit" in r.json()["detail"]
        # another home is unaffected; the sample home needs room for 4
        assert c.post("/api/residents", json=body, headers={"X-Hearth-Home": "home-two"}).status_code == 201
        assert c.post("/api/demo", headers={"X-Hearth-Home": "home-three"}).status_code == 409


def test_too_many_favourites_rejected(tmp_path):
    with TestClient(_app(tmp_path, rate_limiter=False)) as c:
        ents = [{"id": f"x{i}", "name": "x", "type": "artist"} for i in range(31)]
        assert c.post("/api/residents", json={"name": "A", "entities": ents}).status_code == 422


def test_health_payload(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        j = c.get("/api/health").json()
        assert j["ok"] and j["db"] and j["rate_limited"] and j["max_residents_per_home"] == 12


def test_spa_served_for_get_and_head(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Hearth</title>")
    with TestClient(_app(tmp_path, web_dist=dist)) as c:
        assert c.get("/").status_code == 200 and "Hearth" in c.get("/r/abc").text
        assert c.head("/").status_code == 200       # uptime monitors and Caddy health probes
        assert c.get("/api/nope").status_code == 404
