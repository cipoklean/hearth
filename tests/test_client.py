import httpx
import pytest

from hearth.qloo import QlooClient, QlooError, QlooParamError
from hearth.qloo import params as P


def test_rejects_param_not_valid_for_type():
    # filter.release_year.min is a movie param; artist would silently ignore it
    with pytest.raises(QlooParamError, match="not supported"):
        P.validate_insights({"filter.type": "urn:entity:artist", "signal.interests.entities": ["x"],
                             "filter.release_year.min": 1950})
    P.validate_insights({"filter.type": "urn:entity:movie", "signal.interests.entities": ["x"],
                         "filter.release_year.min": 1950})


def test_place_only_params():
    ok = {"filter.type": "urn:entity:place", "filter.location": "6.45,7.5", "filter.price_level.max": 2}
    P.validate_insights(ok)
    with pytest.raises(QlooParamError):
        P.validate_insights({**ok, "filter.type": "urn:entity:book"})


def test_filter_type_required_and_supported():
    with pytest.raises(QlooParamError, match="required"):
        P.validate_insights({"signal.interests.entities": ["x"]})
    with pytest.raises(QlooParamError, match="not supported"):
        P.validate_insights({"filter.type": "urn:entity:music", "signal.interests.entities": ["x"]})


def test_aliases_and_short_names():
    out = P.validate_insights({"filter.type": "urn:entity:video_game", "filter.tags": ["t"]})
    assert out["filter.type"] == "urn:entity:videogame"
    assert P.validate_insights({"filter.type": "movie", "filter.tags": ["t"]})["filter.type"] == "urn:entity:movie"


def test_destination_requires_entities_signal():
    with pytest.raises(QlooParamError, match="requires"):
        P.validate_insights({"filter.type": "urn:entity:destination", "signal.interests.tags": ["t"]})


def test_needs_some_signal_or_filter():
    with pytest.raises(QlooParamError, match="at least one"):
        P.validate_insights({"filter.type": "urn:entity:movie", "take": 5})


def test_value_checks():
    with pytest.raises(QlooParamError):
        P.validate_insights({"filter.type": "urn:entity:movie", "filter.tags": ["t"], "take": 500})
    with pytest.raises(QlooParamError):
        P.validate_insights({"filter.type": "urn:entity:movie", "filter.tags": ["t"], "bias.trends": "max"})


def test_extra_allowed_is_explicit():
    base = {"filter.type": "urn:entity:movie", "filter.tags": ["t"], "feature.explainability": True}
    with pytest.raises(QlooParamError):
        P.validate_insights(base)
    P.validate_insights(base, extra=["feature.explainability"])


def test_compare_and_tags_and_search_tables():
    with pytest.raises(QlooParamError, match="requires"):
        P.validate_compare({"a.signal.interests.entities": ["a"]})
    P.validate_compare({"a.signal.interests.entities": ["a"], "b.signal.interests.entities": ["b"]})
    with pytest.raises(QlooParamError):
        P.validate_tags({"query": "jazz"})  # tags uses filter.query
    with pytest.raises(QlooParamError):
        P.validate_search({"query": "x", "filter.type": "urn:entity:movie"})  # search uses types


async def test_mock_search_and_tags(client):
    res = await client.search("Harbour Lights", types=["movie"])
    assert len([r for r in res if r.name == "Harbour Lights"]) == 2
    assert all(r.properties.get("synthetic") for r in res)
    tags = await client.tags("swing")
    assert tags and tags[0].id.endswith(":swing")


async def test_insights_affinity_and_list_encoding(client):
    ents = await client.insights({"filter.type": "urn:entity:movie",
                                  "signal.interests.entities": ["mock-artist-001"],
                                  "filter.results.entities": ["mock-movie-003", "mock-movie-005"]})
    assert {e.id for e in ents} == {"mock-movie-003", "mock-movie-005"}
    assert ents[0].properties["affinity"] >= ents[1].properties["affinity"]


async def test_compare_path(client):
    data = await client.compare(["mock-artist-001"], ["mock-artist-006"])
    assert any(t["name"] == "Swing" for t in data["results"]["tags"])


async def test_legacy_endpoints_blocked(client):
    with pytest.raises(ValueError):
        await client._get("/recommendations", {})
    with pytest.raises(ValueError):
        await client._get("/recs", {})


async def test_retries_then_succeeds(tmp_path):
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert req.headers["X-Api-Key"] == "k"
        assert req.method == "GET"
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"results": {"entities": []}})

    c = QlooClient("k", transport=httpx.MockTransport(handler), backoff=0, cache_dir=str(tmp_path), use_cache=True)
    assert await c.insights({"filter.type": "movie", "filter.tags": ["t"]}) == []
    assert calls["n"] == 3
    # second call served from the private disk cache
    await c.insights({"filter.type": "movie", "filter.tags": ["t"]})
    assert calls["n"] == 3
    assert list(tmp_path.rglob("*.json"))
    await c.aclose()


async def test_non_retryable_error_raises():
    c = QlooClient("k", transport=httpx.MockTransport(lambda r: httpx.Response(401, text="bad key")), backoff=0)
    with pytest.raises(QlooError) as ei:
        await c.search("x")
    assert ei.value.status == 401
    await c.aclose()


def test_requires_key_outside_mock(monkeypatch):
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    with pytest.raises(QlooError):
        QlooClient(mock=False)
