"""Async Qloo client (GET only).

Base URL: https://hackathon.api.qloo.com  (hackathon keys fail on api.qloo.com)
Auth:     X-Api-Key header, from env QLOO_API_KEY
Paths:    /search, /v2/tags, /v2/insights, /v2/analysis/compare
Never:    /recs, /recommendations (legacy, unsupported for the hackathon)
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Iterable, Mapping

import httpx

from ..models import EntityRef, Tag
from . import params as P
from .cache import DiskCache

log = logging.getLogger("hearth.qloo")

DEFAULT_BASE_URL = "https://hackathon.api.qloo.com"
FORBIDDEN_PATHS = ("/recs", "/recommendations")
RETRY_STATUS = {429, 500, 502, 503, 504}


class QlooError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Qloo HTTP {status}: {message}")
        self.status = status


def _encode(params: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Lists become comma-separated values (Qloo GET convention); bools lowercase."""
    out: list[tuple[str, str]] = []
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, bool):
            v = "true" if v else "false"
        elif isinstance(v, (list, tuple, set)):
            v = ",".join(str(x) for x in v)
        out.append((k, str(v)))
    return out


def env_mock() -> bool:
    return os.environ.get("HEARTH_MOCK", "").strip().lower() in {"1", "true", "yes"}


class QlooClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        mock: bool | None = None,
        timeout: float = 15.0,
        retries: int = 3,
        backoff: float = 0.5,
        cache_dir: str | None = None,
        use_cache: bool | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.mock = env_mock() if mock is None else mock
        self.api_key = api_key if api_key is not None else os.environ.get("QLOO_API_KEY", "")
        self.base_url = (base_url or os.environ.get("QLOO_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.retries = retries
        self.backoff = backoff
        if transport is None and self.mock:
            from .mock import MockQloo
            transport = httpx.MockTransport(MockQloo().handle)
        if not self.mock and not self.api_key and transport is None:
            raise QlooError(401, "QLOO_API_KEY is not set (or set HEARTH_MOCK=1)")
        # Cache real responses only; mock responses are cheap and synthetic.
        if use_cache is None:
            use_cache = not self.mock
        self.cache = DiskCache(cache_dir or os.environ.get("HEARTH_CACHE_DIR", ".cache/qloo")) if use_cache else None
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-Api-Key": self.api_key or "mock", "Accept": "application/json"},
            timeout=httpx.Timeout(timeout),
            transport=transport,
        )
        self.request_count = 0  # network calls actually made (quota guard / tests)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "QlooClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ---- transport -------------------------------------------------------
    async def _get(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        if any(path.startswith(p) for p in FORBIDDEN_PATHS):
            raise ValueError(f"{path} is a legacy endpoint not allowed in the hackathon")
        query = _encode(params)
        key = DiskCache.key(path, query) if self.cache else None
        if key and (hit := self.cache.get(key)) is not None:
            return hit
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                self.request_count += 1
                resp = await self._http.get(path, params=query)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
                log.warning("qloo %s transport error (attempt %d): %s", path, attempt + 1, exc)
            else:
                if resp.status_code == 200:
                    data = resp.json()
                    if key:
                        self.cache.set(key, data)
                    return data
                if resp.status_code == 404:  # Qloo uses 404 for "no results" on search/compare
                    return {"results": []}
                if resp.status_code not in RETRY_STATUS:
                    raise QlooError(resp.status_code, resp.text[:300])
                last = QlooError(resp.status_code, resp.text[:300])
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    await asyncio.sleep(min(float(retry_after), 10.0))
                    continue
            if attempt < self.retries:
                await asyncio.sleep(self.backoff * (2 ** attempt))
        assert last is not None
        if isinstance(last, QlooError):
            raise last
        raise QlooError(0, f"network error: {last}")

    # ---- endpoints -------------------------------------------------------
    async def search(self, query: str, types: Iterable[str] | None = None, take: int = 5,
                     **extra: Any) -> list[EntityRef]:
        p: dict[str, Any] = {"query": query, "take": take, **extra}
        if types:
            p["types"] = [P.normalize_type(t) for t in types]
        data = await self._get("/search", P.validate_search(p))
        return parse_search(data)

    async def tags(self, query: str, tag_types: Iterable[str] | None = None, take: int = 10,
                   **extra: Any) -> list[Tag]:
        p: dict[str, Any] = {"filter.query": query, "take": take, **extra}
        if tag_types:
            p["filter.tag.types"] = list(tag_types)
        data = await self._get("/v2/tags", P.validate_tags(p))
        return parse_tags(data)

    async def insights(self, params: Mapping[str, Any], *, extra_allowed: Iterable[str] = ()) -> list[EntityRef]:
        p = P.validate_insights(params, extra=extra_allowed)
        data = await self._get("/v2/insights", p)
        return parse_insights(data)

    async def compare(self, a_ids: list[str], b_ids: list[str], **extra: Any) -> dict[str, Any]:
        """GET /v2/analysis/compare. Response schema is not documented in detail; returned raw."""
        p = {"a.signal.interests.entities": a_ids, "b.signal.interests.entities": b_ids, **extra}
        return await self._get("/v2/analysis/compare", P.validate_compare(p))


# ---- tolerant response parsing ---------------------------------------------
def _parse_tag(t: Mapping[str, Any]) -> Tag:
    return Tag(id=str(t.get("tag_id") or t.get("id") or t.get("value") or ""), name=str(t.get("name") or ""))


def _parse_entity(e: Mapping[str, Any]) -> EntityRef:
    etype = e.get("subtype") or e.get("type") or ""
    if (not etype or etype == "urn:entity") and e.get("types"):
        etype = next((t for t in e["types"] if t.startswith("urn:entity:")), e["types"][0])
    props = dict(e.get("properties") or {})
    if "popularity" in e:
        props.setdefault("popularity", e["popularity"])
    q = e.get("query") or {}
    if isinstance(q, Mapping) and "affinity" in q:
        props["affinity"] = q["affinity"]
    return EntityRef(
        id=str(e.get("entity_id") or e.get("id")),
        name=str(e.get("name") or ""),
        type=P.normalize_type(etype),
        tags=[_parse_tag(t) for t in (e.get("tags") or []) if isinstance(t, Mapping)],
        properties=props,
    )


def parse_search(data: Mapping[str, Any]) -> list[EntityRef]:
    res = data.get("results") or []
    if isinstance(res, Mapping):
        res = res.get("entities") or []
    return [_parse_entity(e) for e in res]


def parse_insights(data: Mapping[str, Any]) -> list[EntityRef]:
    res = data.get("results") or {}
    ents = res.get("entities") if isinstance(res, Mapping) else res
    return [_parse_entity(e) for e in (ents or [])]


def parse_tags(data: Mapping[str, Any]) -> list[Tag]:
    res = data.get("results") or {}
    tags = res.get("tags") if isinstance(res, Mapping) else res
    return [_parse_tag(t) for t in (tags or [])]
