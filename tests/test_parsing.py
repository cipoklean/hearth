"""Parsing against payloads SHAPED like the live Qloo API (checked 2026-10-24).

Every name, id and number below is invented. No Qloo response data is stored
in this repository.
"""
from hearth.qloo.client import parse_compare, parse_insights, parse_search, parse_tags

SEARCH = {"results": [{
    "entity_id": "SYN-0001", "name": "Synthetic Crooner", "types": ["urn:entity:artist"],
    "popularity": 0.91, "disambiguation": "Synthetic Crooner",
    "properties": {"start_year": 1940},
    "tags": [{"tag_id": "urn:tag:genre:music:syn_swing", "name": "Syn Swing",
              "type": "urn:tag:genre:music", "value": "urn:tag:genre:music:syn_swing"}]}]}

INSIGHTS = {"success": True, "results": {"entities": [
    {"name": "Synthetic Film", "entity_id": "SYN-0100", "type": "urn:entity", "subtype": "urn:entity:movie",
     "properties": {"release_year": 1951, "content_rating": "G"}, "popularity": 0.8,
     "tags": [{"id": "urn:tag:genre:media:syn_musical", "name": "Syn Musical", "type": "urn:tag:genre:media"}],
     "query": {"affinity": 0.912, "measurements": {"audience_growth": 0},
               "explainability": {"signal.interests.entities": [
                   {"entity_id": "SYN-0001", "score": 0.61}, {"entity_id": "SYN-0002", "score": 0.39}]}},
     "disambiguation": "Synthetic Film", "external": {}},
    {"name": "Synthetic Hall", "entity_id": "SYN-0200", "type": "urn:entity", "subtype": "urn:entity:place",
     "properties": {"address": "1 Invented Rd"}, "popularity": 0.7, "tags": [],
     "query": {"affinity": 0.801, "distance": 0, "measurements": {"audience_growth": -1.2}}},
]}}

TAGS = {"results": {"tags": [
    {"parents": [{"type": "urn:entity:artist"}], "type": "urn:tag:genre:music", "id": "urn:tag:genre:music:syn",
     "name": "Syn", "popularity": 0.99, "properties": {}, "tags": []}]}}

COMPARE = {"duration": 3, "results": {
    "tags": [
        {"tag_id": "urn:tag:genre:music:low", "name": "Low", "type": "urn:tag", "subtype": "urn:tag:genre:music",
         "entity_id": "X1", "popularity": 0, "query": {"score": 0.55}},
        {"tag_id": "urn:tag:genre:music:high", "name": "High", "type": "urn:tag", "subtype": "urn:tag:genre:music",
         "entity_id": "X2", "popularity": 0, "query": {"score": 0.99}}],
    "a": [{"tag_id": "urn:tag:theme:qloo:a_only", "name": "A only", "type": "urn:tag",
           "subtype": "urn:tag:theme:qloo", "query": {"count": "1"}}],
    "b": [], "matchEntities": []}}


def test_parse_search_types_list_and_tag_id():
    [e] = parse_search(SEARCH)
    assert e.type == "urn:entity:artist" and e.id == "SYN-0001"
    assert e.properties["popularity"] == 0.91 and e.properties["disambiguation"] == "Synthetic Crooner"
    assert e.tags[0].id == "urn:tag:genre:music:syn_swing" and e.tags[0].type == "urn:tag:genre:music"


def test_parse_insights_subtype_affinity_explainability_distance():
    film, hall = parse_insights(INSIGHTS)
    assert film.type == "urn:entity:movie" and film.properties["affinity"] == 0.912
    assert film.properties["explainability"] == {"SYN-0001": 0.61, "SYN-0002": 0.39}
    assert film.tags[0].id == "urn:tag:genre:media:syn_musical"
    assert hall.type == "urn:entity:place" and hall.properties["distance"] == 0
    assert "explainability" not in hall.properties


def test_parse_tags_and_compare():
    [t] = parse_tags(TAGS)
    assert t.id == "urn:tag:genre:music:syn" and t.type == "urn:tag:genre:music"
    c = parse_compare(COMPARE)
    assert [x["tag"].name for x in c["shared"]] == ["High", "Low"]
    assert c["shared"][0]["tag"].type == "urn:tag:genre:music"
    assert c["a_only"][0].name == "A only" and c["b_only"] == []


def test_parse_tolerates_junk():
    assert parse_insights({}) == [] and parse_search({"results": None}) == []
    assert parse_compare({"results": []}) == {"shared": [], "a_only": [], "b_only": []}
