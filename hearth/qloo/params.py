"""Client-side parameter validation for the Qloo API.

The Qloo API *silently ignores* parameters that are not valid for the chosen
``filter.type`` (it returns 200 with fewer/empty results instead of an error),
so Hearth rejects them before the request is sent.

Source: Qloo "Entity Type Parameter Guide"
https://docs.qloo.com/reference/available-parameters-by-entity-type
plus the Search, Search Tags and Analysis Compare reference pages.
Checked 2026-10-24. Re-check when the docs change.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

# filter.type values the hackathon key supports for /v2/insights
# (Qloo Agentic Hackathon Developer Guide). NOTE: the Insights Deep Dive enum
# spells two of these differently (urn:entity:videogame, urn:entity:locality);
# we follow the hackathon guide and map aliases below.
ENTITY_TYPES: tuple[str, ...] = (
    "urn:entity:artist",
    "urn:entity:book",
    "urn:entity:brand",
    "urn:entity:destination",
    "urn:entity:movie",
    "urn:entity:person",
    "urn:entity:place",
    "urn:entity:podcast",
    "urn:entity:tv_show",
    "urn:entity:video_game",
)

TYPE_ALIASES: dict[str, str] = {
    "urn:entity:videogame": "urn:entity:video_game",
}

# Short domain names Hearth uses in its own API -> Qloo URN
DOMAINS: dict[str, str] = {t.rsplit(":", 1)[1]: t for t in ENTITY_TYPES}

# Parameters common to every entity type in the guide.
_COMMON = frozenset({
    "filter.type",
    "bias.trends",
    "filter.exclude.entities",
    "filter.exclude.tags",
    "operator.exclude.tags",
    "filter.external.exists",
    "operator.filter.external.exists",
    "filter.parents.types",
    "filter.popularity.min",
    "filter.popularity.max",
    "filter.results.entities",
    "filter.results.entities.query",
    "filter.tags",
    "operator.filter.tags",
    "offset",
    "signal.demographics.age",
    "signal.demographics.audiences",
    "signal.demographics.audiences.weight",
    "signal.demographics.gender",
    "signal.interests.entities",
    "signal.interests.tags",
    "take",
})

_GEO = frozenset({
    "filter.geocode.name",
    "filter.geocode.admin1_region",
    "filter.geocode.admin2_region",
    "filter.geocode.country_code",
    "filter.location",
    "filter.location.radius",
    "filter.location.geohash",
    "filter.exclude.location.geohash",
})

INSIGHTS_ALLOWED: dict[str, frozenset[str]] = {
    "urn:entity:artist": _COMMON,
    "urn:entity:book": _COMMON | {"filter.publication_year.min", "filter.publication_year.max"},
    "urn:entity:brand": _COMMON,
    "urn:entity:destination": _COMMON | _GEO,
    "urn:entity:movie": _COMMON | {
        "filter.content_rating",
        "filter.release_year.min", "filter.release_year.max",
        "filter.release_country", "operator.filter.release_country",
        "filter.rating.min", "filter.rating.max",
    },
    "urn:entity:person": _COMMON | {
        "filter.date_of_birth.min", "filter.date_of_birth.max",
        "filter.date_of_death.min", "filter.date_of_death.max",
        "filter.gender",
    },
    "urn:entity:place": _COMMON | _GEO | {
        "bias.quality",
        "filter.address",
        "filter.external.tripadvisor.rating.count.max",
        "filter.external.tripadvisor.rating.count.min",
        "filter.external.tripadvisor.rating.max",
        "filter.external.tripadvisor.rating.min",
        "filter.hotel_class.max", "filter.hotel_class.min",
        "filter.hours",
        "filter.price_level.min", "filter.price_level.max",
        "filter.price_range.from", "filter.price_range.to",
        "filter.properties.business_rating.min", "filter.properties.business_rating.max",
        "filter.properties.resy.rating.min", "filter.properties.resy.rating.max",
        "filter.references_brand",
        "filter.resy.rating_count.min", "filter.resy.rating_count.max",
        "filter.resy.rating.party.min", "filter.resy.rating.party.max",
        "sort_by",
    },
    "urn:entity:podcast": _COMMON,
    "urn:entity:tv_show": _COMMON | {
        "filter.content_rating",
        "filter.finale_year.min", "filter.finale_year.max",
        "filter.latest_known_year.min", "filter.latest_known_year.max",
        "filter.release_year.min", "filter.release_year.max",
        "filter.release_country", "operator.filter.release_country",
        "filter.rating.min", "filter.rating.max",
    },
    "urn:entity:video_game": _COMMON,
}

# Per the guide, destination *requires* signal.interests.entities.
INSIGHTS_REQUIRED: dict[str, frozenset[str]] = {
    t: frozenset({"filter.type"}) for t in ENTITY_TYPES
}
INSIGHTS_REQUIRED["urn:entity:destination"] = frozenset({"filter.type", "signal.interests.entities"})

# Insights needs at least one signal or filter ("at least one valid signal or
# filter is required"); we enforce that client-side too.
_SIGNAL_OR_FILTER_PREFIXES = ("signal.", "filter.")

SEARCH_ALLOWED = frozenset({
    "query", "types", "filter.location", "filter.radius", "filter.exists",
    "filter.tags", "filter.rating", "filter.popularity", "filter.address",
    "operator.filter.tags", "page", "take", "sort_by",
})

TAGS_ALLOWED = frozenset({
    "feature.typo_tolerance", "feature.semantic_search", "filter.results.tags",
    "filter.parents.types", "filter.popularity.min", "filter.popularity.max",
    "filter.query", "filter.tag.types", "page", "take",
})

# GET /v2/analysis/compare  (NOT /v2/insights/compare)
COMPARE_ALLOWED = frozenset({
    "a.signal.interests.entities", "b.signal.interests.entities",
    "filter.type", "filter.entities.query",
    "filter.location.query", "filter.location.radius",
    "filter.exclude.location.query", "filter.exclude.location.radius",
    "filter.subtype", "model", "page", "take", "offset",
})
COMPARE_REQUIRED = frozenset({"a.signal.interests.entities", "b.signal.interests.entities"})

_ENUMS: dict[str, frozenset[str]] = {
    "bias.trends": frozenset({"off", "very_low", "low", "mid", "medium", "high", "very_high"}),
    "operator.filter.tags": frozenset({"union", "intersection"}),
    "operator.exclude.tags": frozenset({"union", "intersection"}),
    "sort_by": frozenset({"affinity", "distance", "rating", "quality"}),
    "signal.demographics.gender": frozenset({"male", "female"}),
    "model": frozenset({"descriptive", "predictive"}),
}

_RANGES: dict[str, tuple[float, float]] = {
    "take": (1, 50),
    "filter.popularity.min": (0, 1),
    "filter.popularity.max": (0, 1),
    "filter.rating.min": (0, 5),
    "filter.rating.max": (0, 5),
    "filter.location.radius": (0, 800000),
    "page": (1, 100),
}


class QlooParamError(ValueError):
    """A request would carry a parameter Qloo would silently ignore or reject."""


def normalize_type(filter_type: str) -> str:
    t = TYPE_ALIASES.get(filter_type, filter_type)
    if t in DOMAINS:  # allow short names like "movie"
        t = DOMAINS[t]
    return t


def _check_values(params: Mapping[str, Any]) -> None:
    for key, allowed in _ENUMS.items():
        if key in params and str(params[key]) not in allowed:
            raise QlooParamError(f"{key}={params[key]!r} not one of {sorted(allowed)}")
    for key, (lo, hi) in _RANGES.items():
        if key in params:
            try:
                v = float(params[key])
            except (TypeError, ValueError) as exc:
                raise QlooParamError(f"{key} must be numeric") from exc
            if not lo <= v <= hi:
                raise QlooParamError(f"{key}={v} outside {lo}..{hi}")


def _check_allowed(params: Iterable[str], allowed: frozenset[str], where: str,
                   extra: frozenset[str]) -> None:
    bad = sorted(set(params) - allowed - extra)
    if bad:
        raise QlooParamError(f"parameters not supported for {where}: {bad}")


def validate_insights(params: Mapping[str, Any], *, extra: Iterable[str] = ()) -> dict[str, Any]:
    """Validate an /v2/insights query. Returns a copy with filter.type normalised.

    ``extra`` lets a caller knowingly send a documented parameter that the
    per-type guide does not list (e.g. ``page``, ``feature.explainability``).
    """
    if "filter.type" not in params:
        raise QlooParamError("filter.type is required for /v2/insights")
    out = dict(params)
    ftype = normalize_type(str(out["filter.type"]))
    if ftype not in INSIGHTS_ALLOWED:
        raise QlooParamError(f"filter.type {out['filter.type']!r} is not supported "
                             f"(use one of {list(ENTITY_TYPES)})")
    out["filter.type"] = ftype
    _check_allowed(out.keys(), INSIGHTS_ALLOWED[ftype], ftype, frozenset(extra))
    missing = INSIGHTS_REQUIRED[ftype] - out.keys()
    if missing:
        raise QlooParamError(f"{ftype} requires {sorted(missing)}")
    if not any(k.startswith(_SIGNAL_OR_FILTER_PREFIXES) and k != "filter.type" for k in out):
        raise QlooParamError("at least one signal.* or filter.* parameter besides filter.type is required")
    _check_values(out)
    return out


def validate_search(params: Mapping[str, Any]) -> dict[str, Any]:
    if not params.get("query"):
        raise QlooParamError("query is required for /search")
    _check_allowed(params.keys(), SEARCH_ALLOWED, "/search", frozenset())
    _check_values({k: v for k, v in params.items() if k in ("page",)})
    return dict(params)


def validate_tags(params: Mapping[str, Any]) -> dict[str, Any]:
    _check_allowed(params.keys(), TAGS_ALLOWED, "/v2/tags", frozenset())
    _check_values({k: v for k, v in params.items() if k in ("take", "page", "filter.popularity.min",
                                                              "filter.popularity.max")})
    return dict(params)


def validate_compare(params: Mapping[str, Any]) -> dict[str, Any]:
    _check_allowed(params.keys(), COMPARE_ALLOWED, "/v2/analysis/compare", frozenset())
    missing = COMPARE_REQUIRED - params.keys()
    if missing:
        raise QlooParamError(f"/v2/analysis/compare requires {sorted(missing)}")
    _check_values({k: v for k, v in params.items() if k in ("take", "page", "model")})
    return dict(params)
