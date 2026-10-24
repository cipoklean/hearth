"""Era (a Hearth setting) and gentle-rating filters for film/TV picks and swaps. Mock data only."""
import sqlite3

import pytest
import pytest_asyncio

from hearth.era import ERA_LABEL, filter_notes, out_of_era, ranked_filters
from hearth.models import EntityRef, Need, Profile
from hearth.planner import group_pick, weekly_plan
from hearth.qloo.params import QlooParamError, validate_insights
from hearth.storage import Store
from hearth.verifier import Candidate, verify


def _film(eid, year, weight=1.0):
    return EntityRef(id=eid, name=eid, type="urn:entity:movie", properties={"release_year": year}, weight=weight)


def test_era_auto_from_newest_favourite():
    p = Profile(name="Rose", entities=[_film("a", 1942), _film("b", 1953)])
    assert p.era and p.era.max_year == 1963 and p.era.source == "auto"
    assert p.era.label == ERA_LABEL


def test_era_ignores_disliked_and_non_film_favourites():
    art = EntityRef(id="x", name="X", type="urn:entity:artist", properties={"release_year": 2010})
    p = Profile(entities=[_film("a", 1950), _film("b", 2001, weight=-1.0), art], disliked=["b"])
    assert p.era.max_year == 1960


def test_era_none_without_dated_favourites_and_when_off():
    assert Profile(entities=[EntityRef(id="x", name="X", type="urn:entity:artist")]).era is None
    assert Profile(entities=[_film("a", 1950)], era_mode="off").era is None


def test_era_set_by_staff_wins():
    p = Profile(entities=[_film("a", 1950)], era_mode="year", era_max_year=1975)
    assert p.era.max_year == 1975 and p.era.source == "set"


def test_era_year_bounds():
    with pytest.raises(ValueError):
        Profile(era_mode="year", era_max_year=1500)


def test_ranked_filters_movie_and_tv_only():
    p = Profile(name="Rose", entities=[_film("a", 1953)], needs=[Need.mild_content])
    f = ranked_filters(p, "urn:entity:movie")
    assert f["filter.release_year.max"] == 1963
    assert "G" in f["filter.content_rating"] and "R" not in f["filter.content_rating"]
    assert ranked_filters(p, "urn:entity:tv_show")["filter.release_year.max"] == 1963
    assert ranked_filters(p, "urn:entity:artist") == {}
    assert ranked_filters(Profile(), "urn:entity:movie") == {}
    # the filters pass Hearth's own parameter validation for both types
    for t in ("urn:entity:movie", "urn:entity:tv_show"):
        validate_insights({"filter.type": t, "signal.interests.entities": ["a"], **ranked_filters(p, t)})
    assert any(n.startswith(ERA_LABEL) for n in filter_notes(p, "urn:entity:movie"))


def test_param_validation_for_era_filters():
    base = {"filter.type": "urn:entity:movie", "signal.interests.entities": ["a"]}
    validate_insights({**base, "filter.release_year.max": 1965, "filter.release_year.min": 1930})
    validate_insights({**base, "filter.content_rating": "G,PG,Approved"})
    for bad in ({"filter.release_year.max": "sixties"}, {"filter.release_year.max": 1.5},
                {"filter.release_year.max": 3000}, {"filter.content_rating": "G,Family"},
                {"filter.release_year.min": 1970, "filter.release_year.max": 1960}):
        with pytest.raises(QlooParamError):
            validate_insights({**base, **bad})
    with pytest.raises(QlooParamError):  # artists silently ignore it on the live API
        validate_insights({"filter.type": "urn:entity:artist", "signal.interests.entities": ["a"],
                           "filter.release_year.max": 1965})


def test_out_of_era():
    p = Profile(name="Rose", entities=[_film("a", 1952)])
    assert "after Rose's era" in out_of_era(_film("z", 1997), p)
    assert out_of_era(_film("z", 1954), p) is None
    assert out_of_era(EntityRef(id="q", name="Q", type="urn:entity:movie"), p) is None  # year unknown


@pytest_asyncio.fixture
async def rose(client):
    """Mock stand-in: likes The Marlow Sisters and Dancing on the Pier (1952) -> era up to 1962."""
    marlow = (await client.search("The Marlow Sisters", types=["artist"], take=1))[0]
    pier = (await client.search("Dancing on the Pier", types=["movie"], take=1))[0]
    return Profile(resident_id="rose", name="Rose", entities=[marlow, pier])


async def test_film_night_and_swaps_stay_in_era(client, rose):
    # Without the era, Qloo's (mock) top film for Rose is from 1997.
    off = await weekly_plan(client, rose.model_copy(update={"era_mode": "off"}))
    film_off = next(i for i in off.items if i.slot == "film_night")
    assert film_off.entity.properties["release_year"] == 1997

    plan = await weekly_plan(client, rose)
    film = next(i for i in plan.items if i.slot == "film_night")
    assert film.entity.properties["release_year"] <= 1962
    assert any(n.startswith(ERA_LABEL) for n in film.check.evidence.notes)
    # verdict measured against the unfiltered best, not the narrowed list
    assert film.check.evidence.best_available_affinity == film_off.entity.properties["affinity"]

    swapped = await weekly_plan(client, rose, skip_ids=[film.entity.id])
    film2 = next(i for i in swapped.items if i.slot == "film_night")
    assert film2.entity.id != film.entity.id and film2.entity.properties["release_year"] <= 1962


async def test_verify_flags_out_of_era_and_swaps_in_era(client, rose):
    rep = await verify(client, rose, [Candidate(name="The Village Choir", domain="movie"),
                                      Candidate(name="Letters to Lagos", domain="movie")])
    for r in rep.results:
        assert any("after Rose's era" in n for n in r.evidence.notes)
        assert r.swap is not None and r.swap.entity.properties["release_year"] <= 1962
        assert "within their era" in r.swap.reason


async def test_group_pick_keeps_suggestions_in_everyones_era(client, rose, bayo):
    g = await group_pick(client, [rose, bayo], "movie")
    assert g.pick is not None and g.pick.properties["release_year"] <= 1962
    assert any(ERA_LABEL in x.reason for x in g.excluded)
    assert any(n.startswith(ERA_LABEL) for n in g.notes)


async def test_mild_content_filter_reaches_qloo(client):
    pier = (await client.search("Dancing on the Pier", types=["movie"], take=1))[0]
    grim = (await client.search("Midnight in the Cellar", types=["movie"], take=1))[0]
    p = Profile(name="Ada", entities=[pier, grim], needs=[Need.mild_content], era_mode="off")
    plan = await weekly_plan(client, p)
    film = next(i for i in plan.items if i.slot == "film_night")
    assert film.entity.properties["content_rating"] in {"G", "PG"}
    assert any("Gentle films" in n for n in film.check.evidence.notes)


def test_storage_round_trip_and_migration(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)  # a database from before the era columns existed
    con.executescript("""
      CREATE TABLE residents (id TEXT PRIMARY KEY, name TEXT NOT NULL, needs TEXT NOT NULL DEFAULT '[]',
                              home_id TEXT NOT NULL DEFAULT 'default');
      CREATE TABLE resident_entities (resident_id TEXT NOT NULL, entity_id TEXT NOT NULL, name TEXT NOT NULL,
        type TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '[]', weight REAL NOT NULL DEFAULT 1.0,
        disliked INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (resident_id, entity_id));
      INSERT INTO residents (id, name) VALUES ('old1', 'Olive');""")
    con.commit()
    con.close()
    s = Store(str(db))
    old = s.get_profile("old1")
    assert old.era_mode == "auto" and old.era is None
    p = s.create_resident("Rose", [_film("m1", 1953)], [], [])
    assert p.entities[0].properties["release_year"] == 1953 and p.era.max_year == 1963
    s.set_era(p.resident_id, "year", 1970)
    assert s.get_profile(p.resident_id).era.max_year == 1970
    s.set_era(p.resident_id, "off", None)
    assert s.get_profile(p.resident_id).era is None
    s.close()
