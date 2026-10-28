from hearth.constraints.rules import unasked_dark
from hearth.models import EntityRef, Profile, Tag
from hearth.verifier import ResolutionStatus
from hearth.verifier.core import match_candidates


def _m(id, name, pop=0.5):
    return EntityRef(id=id, name=name, type="urn:entity:movie", properties={"popularity": pop})


def test_sequel_number_never_swapped():
    res = match_candidates("Fast & Furious 9", [_m("a", "Fast & Furious 6"), _m("b", "Fast & Furious")])
    assert res.status is ResolutionStatus.cannot_verify
    assert "number" in res.reason


def test_sequel_number_kept_when_it_matches():
    res = match_candidates("Fast and Furious 9", [_m("a", "Fast & Furious 6"), _m("b", "Fast & Furious 9")])
    assert res.status is ResolutionStatus.resolved and res.entity.id == "b"


def test_roman_and_digits_agree():
    res = match_candidates("Rocky 2", [_m("a", "Rocky II"), _m("b", "Rocky IV")])
    assert res.entity is not None and res.entity.id == "a"


CRIME = Tag(id="urn:tag:genre:media:crime", name="Crime")
DRAMA = Tag(id="urn:tag:genre:media:drama", name="Drama")


def test_dark_film_not_suggested_without_dark_favourites():
    fela = EntityRef(id="fela", name="Fela Kuti", type="urn:entity:artist",
                     tags=[Tag(id="urn:tag:genre:music:funk", name="Funk")])
    p = Profile(name="Ada", entities=[fela])
    fool = EntityRef(id="fool", name="The Fool", type="urn:entity:movie", tags=[CRIME, DRAMA])
    assert unasked_dark(fool, p) is not None
    gentle = EntityRef(id="g", name="Roman Holiday", type="urn:entity:movie", tags=[DRAMA])
    assert unasked_dark(gentle, p) is None


def test_dark_film_ok_when_favourites_share_it():
    fav = EntityRef(id="gf", name="The Godfather", type="urn:entity:movie", tags=[CRIME, DRAMA])
    p = Profile(name="Earl", entities=[fav])
    other = EntityRef(id="x", name="Chinatown", type="urn:entity:movie", tags=[CRIME])
    assert unasked_dark(other, p) is None
    assert unasked_dark(fav, p) is None
