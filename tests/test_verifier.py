from hearth.constraints import entity_filter
from hearth.models import EntityRef, Profile
from hearth.verifier import (Candidate, ResolutionStatus, Verdict, classify, match_candidates,
                             relative_fit, verify)


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
    assert classify(0.8) is Verdict.good
    assert classify(0.6) is Verdict.weak
    assert classify(0.2) is Verdict.poor


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
    assert good.evidence.qloo_affinity and good.evidence.relative_fit >= 0.8
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
