from hearth.constraints import (LABEL, Outcome, check_dish, check_entity, dish_library, dishes_for,
                                passes)
from hearth.models import EntityRef, Need, Tag


def movie(rating, mins, *tags):
    return EntityRef(id="m", name="M", type="urn:entity:movie",
                     properties={"content_rating": rating, "duration": mins},
                     tags=[Tag(id=f"urn:tag:genre:media:{t}") for t in tags])


def place(*tags):
    return EntityRef(id="p", name="P", type="urn:entity:place", tags=[Tag(id=f"urn:tag:category:place:{t}") for t in tags])


def test_labelled_not_qloo():
    res = check_entity(movie("G", 90), [Need.mild_content])
    assert res and all(r.label == LABEL == "Hearth rule, not Qloo" for r in res)


def test_film_rules():
    assert passes(check_entity(movie("G", 90, "musical"), [Need.mild_content, Need.short_duration]))
    assert not passes(check_entity(movie("R", 90), [Need.mild_content]))
    assert not passes(check_entity(movie("PG", 90, "horror"), [Need.mild_content]))
    assert not passes(check_entity(movie("G", 140), [Need.short_duration]))
    r = check_entity(movie("PG-13", 90), [Need.mild_content])[0]
    assert r.outcome is Outcome.unknown


def test_wheelchair_unknown_until_staff_confirm():
    r = check_entity(place("garden"), [Need.wheelchair_access])[0]
    assert r.outcome is Outcome.unknown and passes([r])
    assert check_entity(place("garden"), [Need.wheelchair_access], {"step_free": True})[0].outcome is Outcome.pass_
    assert not passes(check_entity(place("garden"), [Need.wheelchair_access], {"step_free": False}))


def test_quiet_setting():
    assert not passes(check_entity(place("nightclub"), [Need.quiet_setting]))
    assert check_entity(place("garden"), [Need.quiet_setting], {"quiet": True})[0].outcome is Outcome.pass_
    metal = EntityRef(id="a", name="A", type="urn:entity:artist", tags=[Tag(id="urn:tag:genre:music:heavy_metal")])
    assert not passes(check_entity(metal, [Need.quiet_setting]))


def test_dishes():
    assert dish_library()
    soft_low_salt = dishes_for("west_african", [Need.soft_food, Need.low_salt])
    assert soft_low_salt and all(d.soft and d.low_salt for d in soft_low_salt)
    jollof = next(d for d in dish_library() if d.name.startswith("Jollof"))
    assert not passes(check_dish(jollof, [Need.soft_food]))
    assert dishes_for("unknown_cuisine", []) == []
