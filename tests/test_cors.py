from fastapi.testclient import TestClient

from hearth.api import create_app
from hearth.qloo import QlooClient


def _client(tmp_path):
    return TestClient(create_app(client=QlooClient(mock=True), db_path=str(tmp_path / "t.db"),
                                 rate_limiter=False))


def test_vercel_origin_preflight_allowed(tmp_path):
    with _client(tmp_path) as c:
        r = c.options("/api/health", headers={
            "Origin": "https://hearth-demo.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-hearth-home,content-type"})
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == "https://hearth-demo.vercel.app"


def test_other_origin_not_allowed(tmp_path):
    with _client(tmp_path) as c:
        r = c.get("/api/health", headers={"Origin": "https://evil.example.com"})
        assert "access-control-allow-origin" not in r.headers
