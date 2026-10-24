from hearth.models import EntityRef, Tag
from hearth.planner import choose, group_pick, rank_cuisines, weekly_plan
from hearth.verifier import Candidate


def test_rank_cuisines_pure():
    P = "urn:tag:genre:place:restaurant:"
    places = [EntityRef(id="1", name="A", type="urn:entity:place", tags=[Tag(id=P + "italian", name="Italian")],
                        properties={"affinity": 0.9}),
              EntityRef(id="2", name="B", type="urn:entity:place", tags=[Tag(id=P + "caribbean", name="Caribbean")],
                        properties={"affinity": 0.5})]
    assert [c[0] for c in rank_cuisines(places)] == ["italian", "caribbean"]


async def test_weekly_plan_shape_and_rules(client, ada):
    plan = await weekly_plan(client, ada)
    slots = [(i.day, i.slot) for i in plan.items]
    assert slots[0] == ("Monday", "meal_theme") and ("Thursday", "film_night") in slots
    film = next(i for i in plan.items if i.slot == "film_night")
    assert film.entity and film.entity.properties["content_rating"] in {"G", "PG"}  # mild_content
    assert film.check and film.check.evidence.qloo_affinity is not None
    meals = [i for i in plan.items if i.slot == "meal_theme"]
    assert all(d.soft for m in meals for d in m.dishes)  # soft_food
    assert meals[0].title != meals[1].title
    outing = next(i for i in plan.items if i.slot == "outing")
    assert any("step-free" in n for n in outing.notes)  # unknown -> staff to confirm


async def test_weekly_plan_deterministic(client, ada):
    a = await weekly_plan(client, ada)
    b = await weekly_plan(client, ada)
    assert a.model_dump() == b.model_dump()


async def test_group_pick_names_who_is_left_out(client, ada, bayo, cy):
    g = await group_pick(client, [ada, bayo, cy], "movie")
    assert g.pick is not None
    assert g.pick.properties["content_rating"] in {"G", "PG"}  # Ada's mild_content excludes R films
    assert any("Hearth rule" in x.reason for x in g.excluded)
    left = {l.name: l for l in g.left_out}
    assert "Cy" in left and left["Cy"].alternative is not None
    assert left["Cy"].alternative.id != g.pick.id
    assert {f.name for f in g.fits} == {"Ada", "Bayo", "Cy"}


async def test_group_pick_from_given_candidates(client, ada, bayo):
    g = await group_pick(client, [ada, bayo], "movie", candidates=[
        Candidate(name="Dust Road West", domain="movie"),
        Candidate(name="Dancing on the Pier", domain="movie"),
        Candidate(name="Harbour Lights", domain="movie")])
    assert g.pick.name == "Dancing on the Pier"
    assert len(g.unresolved) == 1  # ambiguous Harbour Lights reported, not guessed


def test_choose_prefers_more_people_covered():
    from hearth.models import Profile
    a, b = Profile(resident_id="a"), Profile(resident_id="b")
    x = EntityRef(id="x", name="X", type="urn:entity:movie")
    y = EntityRef(id="y", name="Y", type="urn:entity:movie")
    rel = {"a": {"x": 1.0, "y": 0.6}, "b": {"x": 0.1, "y": 0.6}}
    assert choose([x, y], rel, [a, b]).id == "y"
