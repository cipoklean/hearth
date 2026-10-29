from hearth.qloo.client import parse_insights, _tidy_place_name


def _ent(name, t="urn:entity:tv_show"):
    return {"entity_id": name, "name": name, "subtype": t}


def test_racist_caricature_titles_never_returned():
    data = {"results": {"entities": [_ent("The Amos 'n Andy Show"), _ent("I Love Lucy"),
                                     _ent("Song of the South", "urn:entity:movie")]}}
    assert [e.name for e in parse_insights(data)] == ["I Love Lucy"]


def test_lowercase_landmark_names_are_title_cased():
    assert _tidy_place_name("Big ben") == "Big Ben"
    assert _tidy_place_name("Tower of london") == "Tower of London"
    assert _tidy_place_name("Kew Gardens") == "Kew Gardens"
    assert _tidy_place_name("Café 1") == "Café 1"


def test_place_entities_get_tidied():
    data = {"results": {"entities": [_ent("Big ben", "urn:entity:place")]}}
    assert parse_insights(data)[0].name == "Big Ben"
