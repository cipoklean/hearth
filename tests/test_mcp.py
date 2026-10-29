import pytest
from fastapi.testclient import TestClient

from hearth.api import create_app
from hearth.qloo import QlooClient

ADA = {"name": "Ada", "favourites": [{"name": "The Marlow Sisters", "domain": "artist"}],
       "needs": ["soft_food", "mild_content"]}


@pytest.fixture
def api(tmp_path):
    app = create_app(client=QlooClient(mock=True), db_path=str(tmp_path / "t.db"), rate_limiter=False)
    with TestClient(app) as c:
        yield c


def rpc(api, method, params=None, id=1):
    r = api.post("/mcp", json={"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}},
                 headers={"accept": "application/json, text/event-stream"})
    assert r.status_code == 200, r.text
    return r.json()


def test_handshake_and_tools(api):
    init = rpc(api, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "t", "version": "0"}})["result"]
    assert init["serverInfo"]["name"] == "hearth" and init["protocolVersion"] == "2025-06-18"
    assert api.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    names = {t["name"] for t in rpc(api, "tools/list")["result"]["tools"]}
    assert names == {"check_picks", "plan_week", "group_pick", "find_entity"}


def test_check_picks(api):
    res = rpc(api, "tools/call", {"name": "check_picks", "arguments": {
        **ADA, "candidates": [{"name": "Dancing on the Pier", "domain": "movie"},
                              {"name": "Not A Real Film 123", "domain": "movie"}]}})["result"]
    assert res["isError"] is False
    data = res["structuredContent"]
    assert data["favourites_used"][0]["name"] == "The Marlow Sisters"
    assert len(data["results"]) == 2


def test_plan_week_and_group(api):
    wp = rpc(api, "tools/call", {"name": "plan_week", "arguments": ADA})["result"]
    assert wp["isError"] is False and len(wp["structuredContent"]["items"]) == 28
    gp = rpc(api, "tools/call", {"name": "group_pick", "arguments": {
        "people": [ADA, {"name": "Bayo", "favourites": [
            {"name": "Teddy Okafor & His Highlife Band", "domain": "artist"}]}], "domain": "movie"}})["result"]
    assert gp["isError"] is False and "pick" in gp["structuredContent"]


def test_bad_input_is_a_tool_error(api):
    res = rpc(api, "tools/call", {"name": "check_picks", "arguments": {"favourites": []}})["result"]
    assert res["isError"] is True
    res = rpc(api, "tools/call", {"name": "plan_week", "arguments": {
        "favourites": [{"name": "zzzz qqqq", "domain": "artist"}]}})["result"]
    assert res["isError"] is True and "favourites" in res["content"][0]["text"]
    assert rpc(api, "nope")["error"]["code"] == -32601


def test_mcp_is_rate_limited():
    from hearth.ratelimit import buckets_for
    assert buckets_for("POST", "/mcp") == ["api", "qloo"]
