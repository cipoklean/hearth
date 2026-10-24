from hearth.constraints import entity_filter
from hearth.models import EntityRef, Profile
from hearth.verifier import (DEFAULT_THRESHOLDS, Candidate, ResolutionStatus, Verdict, classify,
                             match_candidates, relative_fit, verify)


def _e(i, name):
    return EntityRef(id=i, name=name, type="urn:entity:movie")


def test_match_candidates_pure():
    assert match_candidates("x", []).status is ResolutionStatus.cannot_verify
    r = match_candidates("Harbour Lights", [_e("1", "Harbour Lights"), _e("2", "Harbour Lights")])
    assert r.status is ResolutionStatus.ambiguous and len(r.options) == 2
    r = match_candidates("harbour lights!", [_e("1", "Harbour Lights"), _e("2", "Harbor Nights")])
    assert r.status is ResolutionStatus.resolved and r.entity.id == "1"
    assert match_candidates("zzz", [_e("1", "Harbour Lights")]).status is ResolutionStatus.cannot_verify


def test_classify_and_relative_fit():
    assert relative_fit(0.4, 0.5) == 0.8
    assert relative_fit(0.4, 0) == 0.0
    assert classify(0.97) is Verdict.good
    assert classify(0.90) is Verdict.weak
    assert classify(0.80) is Verdict.poor


def test_classify_per_type_and_absolute_floors():
    A, M, PL, B = "urn:entity:artist", "urn:entity:movie", "urn:entity:place", "urn:entity:book"
    assert classify(0.96, affinity=0.93, etype=A) is Verdict.good
    assert classify(0.96, affinity=0.83, etype=M) is Verdict.weak     # relative ok, absolute too low for good
    assert classify(0.90, affinity=0.75, etype=A) is Verdict.poor     # below the absolute floor
    assert classify(0.80, affinity=0.80, etype=M) is Verdict.poor
    assert classify(0.93, affinity=0.70, etype=PL) is Verdict.weak    # place: relative only (provisional)
    assert classify(0.89, affinity=0.70, etype=PL) is Verdict.poor
    assert classify(0.95, affinity=0.50, etype=B) is Verdict.good     # uncalibrated type: relative only
    assert DEFAULT_THRESHOLDS.for_type(A).status == "calibrated"
    assert DEFAULT_THRESHOLDS.for_type(B).status == "uncalibrated"


def test_duplicate_names_resolve_to_far_more_popular():
    def m(i, pop, year):
        return EntityRef(id=i, name="Roman Holiday", type="urn:entity:movie",
                         properties={"popularity": pop, "release_year": year})
    r = match_candidates("Roman Holiday", [m("a", 0.99, 1953), m("b", 0.0, 1987), m("c", 0.0, 2017)])
    assert r.status is ResolutionStatus.resolved and r.entity.id == "a" and len(r.options) == 2
    r = match_candidates("Roman Holiday", [m("a", 0.99, 2019), m("b", 0.97, 1994)])
    assert r.status is ResolutionStatus.ambiguous and r.options[0].id == "a"


def test_generic_word_is_not_a_match():
    res = [EntityRef(id="1", name="Manchester Orchestra", type="urn:entity:artist"),
           EntityRef(id="2", name="The Cinematic Orchestra", type="urn:entity:artist")]
    assert match_candidates("Zzqx Nonexistent Orchestra", res).status is ResolutionStatus.cannot_verify
    r = match_candidates("Glen Miller Orchestra", [EntityRef(id="3", name="Glenn Miller Orchestra", type="urn:entity:artist")])
    assert r.status is ResolutionStatus.resolved


def test_leading_favourite():
    from hearth.verifier import SignalContribution as S, leading_favourite
    assert leading_favourite([S(entity_id="a", share=1.0)]) is None
    assert leading_favourite([S(entity_id="a", share=0.26), S(entity_id="b", share=0.25),
                              S(entity_id="c", share=0.25), S(entity_id="d", share=0.24)]) is None
    lead = leading_favourite([S(entity_id="a", share=0.25), S(entity_id="b", share=0.24),
                              S(entity_id="c", share=0.2), S(entity_id="d", share=0.16), S(entity_id="e", share=0.15)])
    assert lead and lead.entity_id == "a"


async def test_verify_batches_calls_per_domain(client, ada):
    names = ["Dancing on the Pier", "Midnight in the Cellar", "Iron Front", "Dust Road West"]
    before = client.request_count
    await verify(client, ada, [Candidate(name=n, domain="movie") for n in names])
    # 4 searches + 1 ranked list + 1 batch score
    assert client.request_count - before == len(names) + 2


async def test_verdicts_end_to_end(client, ada):
    rep = await verify(client, ada, [
        Candidate(name="Dancing on the Pier", domain="movie"),
        Candidate(name="Midnight in the Cellar", domain="movie"),
        Candidate(name="Harbour Lights", domain="movie"),
        Candidate(name="A Film That Does Not Exist", domain="movie"),
        Candidate(name="Anything", domain="spaceship"),
    ])
    v = {r.candidate.name: r for r in rep.results}
    good = v["Dancing on the Pier"]
    assert good.verdict is Verdict.good
    assert good.evidence.qloo_affinity and good.evidence.relative_fit >= 0.94
    assert good.evidence.threshold_status == "calibrated"
    poor = v["Midnight in the Cellar"]
    assert poor.verdict is Verdict.poor
    assert poor.swap and poor.swap.qloo_affinity > poor.evidence.qloo_affinity
    assert v["Harbour Lights"].verdict is Verdict.needs_confirmation
    assert len(v["Harbour Lights"].resolution.options) == 2
    assert v["A Film That Does Not Exist"].verdict is Verdict.cannot_verify
    assert v["Anything"].verdict is Verdict.cannot_verify
    assert rep.counts["good"] == 1


async def test_confirmed_id_resolves_ambiguity(client, ada):
    rep = await verify(client, ada, [Candidate(name="Harbour Lights", domain="movie", entity_id="mock-movie-001")])
    r = rep.results[0]
    assert r.resolution.status is ResolutionStatus.resolved
    assert r.verdict in (Verdict.good, Verdict.weak)
    assert r.resolution.entity.tags  # Qloo tags attached as evidence source


async def test_shared_tag_evidence(client, ada):
    rep = await verify(client, ada, [Candidate(name="The Jivetones", domain="artist")])
    names = {t.name for t in rep.results[0].evidence.shared_tags}
    assert "Swing" in names


async def test_swap_respects_care_rules(client, ada):
    rep = await verify(client, ada, [Candidate(name="Iron Front", domain="movie")],
                       swap_filter=entity_filter(ada.needs))
    r = rep.results[0]
    assert r.verdict is not Verdict.good
    assert r.swap is not None
    assert r.swap.entity.properties.get("content_rating") in {"G", "PG"}


async def test_empty_profile_cannot_verify(client):
    rep = await verify(client, Profile(name="New"), [Candidate(name="Dancing on the Pier", domain="movie")])
    assert rep.results[0].verdict is Verdict.cannot_verify


async def test_disliked_is_poor(client, ada):
    ada.disliked.append("mock-movie-003")
    rep = await verify(client, ada, [Candidate(name="Dancing on the Pier", domain="movie")])
    assert rep.results[0].verdict is Verdict.poor


async def test_known_favourite_is_good_without_scoring(client, ada):
    before = client.request_count
    rep = await verify(client, ada, [Candidate(name="The Marlow Sisters", domain="artist")])
    r = rep.results[0]
    assert r.verdict is Verdict.good and "favourite" in r.evidence.notes[0]
    assert client.request_count - before == 1  # search only
