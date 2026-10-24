"""Offline stand-in for the Qloo API (HEARTH_MOCK=1).

Serves responses shaped like Qloo's from a small, invented catalogue
(fixtures/synthetic_catalog.json). Affinity is a deterministic toy formula over
tag overlap plus tag "families" (to imitate cross-domain links). It is NOT a
model of Qloo and its numbers mean nothing outside tests and demos.
"""
from __future__ import annotations

import difflib
import json
from functools import cached_property
from pathlib import Path
from typing import Any

import httpx

from . import params as P

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_catalog.json"


def _split(v: str | None) -> list[str]:
    return [x for x in (v or "").split(",") if x]


def _norm(s: str) -> str:
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in s).split())


class MockQloo:
    def __init__(self, fixture: Path = FIXTURE):
        self.data = json.loads(Path(fixture).read_text())

    @cached_property
    def tags(self) -> dict[str, dict[str, Any]]:
        return {t["id"]: t for t in self.data["tags"]}

    @cached_property
    def entities(self) -> dict[str, dict[str, Any]]:
        return {e["entity_id"]: e for e in self.data["entities"]}

    # ---- rendering -------------------------------------------------------
    def _render(self, e: dict[str, Any], affinity: float | None = None) -> dict[str, Any]:
        out = {
            "name": e["name"],
            "entity_id": e["entity_id"],
            "type": "urn:entity",
            "subtype": e["type"],
            "types": [e["type"]],
            "popularity": e["popularity"],
            "properties": dict(e["properties"]),
            "tags": [{"tag_id": t, "id": t, "name": self.tags[t]["name"], "type": self.tags[t]["type"]}
                     for t in e["tags"]],
        }
        if affinity is not None:
            out["query"] = {"affinity": affinity}
        return out

    def _families(self, tag_ids: list[str]) -> set[str]:
        return {f for t in tag_ids if t in self.tags for f in self.tags[t]["families"]}

    def affinity(self, e: dict[str, Any], sig_tags: set[str], sig_fams: set[str]) -> float:
        ctags = e["tags"]
        direct = len(set(ctags) & sig_tags) / len(ctags) if ctags else 0.0
        cf = self._families(ctags)
        fam = len(cf & sig_fams) / len(cf) if cf else 0.0
        return round(min(0.99, 0.1 + 0.45 * direct + 0.45 * fam + 0.05 * e["popularity"]), 4)

    # ---- handler ---------------------------------------------------------
    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            return httpx.Response(404, json={"error": "No path matching request parameters"})
        if not request.headers.get("X-Api-Key"):
            return httpx.Response(401, json={"error": "No API key found in request"})
        q = dict(request.url.params)
        path = request.url.path
        try:
            if path == "/search":
                body = self.search(q)
            elif path == "/v2/tags":
                body = self.tag_search(q)
            elif path == "/v2/insights":
                body = self.insights(q)
            elif path == "/v2/analysis/compare":
                body = self.compare(q)
            else:
                return httpx.Response(404, json={"error": f"unknown path {path}"})
        except _HTTP as err:
            return httpx.Response(err.status, json={"error": err.msg})
        body["_synthetic"] = True
        return httpx.Response(200, json=body)

    def search(self, q: dict[str, str]) -> dict[str, Any]:
        query = _norm(q.get("query", ""))
        types = set(_split(q.get("types")))
        take = int(q.get("take", 10))
        scored = []
        for e in self.entities.values():
            if types and e["type"] not in types:
                continue
            name = _norm(e["name"])
            score = 1.0 if name == query else difflib.SequenceMatcher(None, query, name).ratio()
            if query and query in name:
                score = max(score, 0.8)
            if score >= 0.55:
                scored.append((score, e))
        scored.sort(key=lambda x: (-x[0], -x[1]["popularity"], x[1]["entity_id"]))
        return {"results": [self._render(e) for _, e in scored[:take]]}

    def tag_search(self, q: dict[str, str]) -> dict[str, Any]:
        query = q.get("filter.query", "").lower()
        types = set(_split(q.get("filter.tag.types")))
        take = int(q.get("take", 20))
        hits = [t for t in self.tags.values()
                if (not query or query in t["name"].lower() or query in t["id"])
                and (not types or t["type"] in types)]
        return {"success": True, "results": {"tags": [
            {"id": t["id"], "name": t["name"], "types": [t["type"]]} for t in hits[:take]]}}

    def insights(self, q: dict[str, str]) -> dict[str, Any]:
        ftype = q.get("filter.type")
        if not ftype:
            raise _HTTP(400, "filter.type is required")
        ftype = P.normalize_type(ftype)
        if ftype not in P.ENTITY_TYPES:
            raise _HTTP(403, f"You do not have permission to access {ftype}")
        sig_ents = _split(q.get("signal.interests.entities"))
        sig_tag_ids = _split(q.get("signal.interests.tags"))
        if ftype == "urn:entity:destination" and not sig_ents:
            raise _HTTP(400, "signal.interests.entities is required for destination")
        has_any = any(k.startswith(("signal.", "filter.")) and k != "filter.type" for k in q)
        if not has_any:
            raise _HTTP(400, "at least one valid signal or filter is required")
        sig_tags = set(sig_tag_ids)
        for eid in sig_ents:
            if eid in self.entities:
                sig_tags |= set(self.entities[eid]["tags"])
        sig_fams = self._families(list(sig_tags))
        pool = [e for e in self.entities.values() if e["type"] == ftype]
        if only := set(_split(q.get("filter.results.entities"))):
            pool = [e for e in pool if e["entity_id"] in only]
        if excl := set(_split(q.get("filter.exclude.entities"))):
            pool = [e for e in pool if e["entity_id"] not in excl]
        if ftags := set(_split(q.get("filter.tags"))):
            pool = [e for e in pool if ftags & set(e["tags"])]
        if xtags := set(_split(q.get("filter.exclude.tags"))):
            pool = [e for e in pool if not xtags & set(e["tags"])]
        scored = [(self.affinity(e, sig_tags, sig_fams) if (sig_tags or sig_ents) else e["popularity"], e)
                  for e in pool]
        scored.sort(key=lambda x: (-x[0], x[1]["entity_id"]))
        offset = int(q.get("offset", 0))
        take = int(q.get("take", 20))
        return {"success": True, "results": {"entities": [
            self._render(e, a) for a, e in scored[offset:offset + take]]}}

    def compare(self, q: dict[str, str]) -> dict[str, Any]:
        a = _split(q.get("a.signal.interests.entities"))
        b = _split(q.get("b.signal.interests.entities"))
        ta = {t for i in a if i in self.entities for t in self.entities[i]["tags"]}
        tb = {t for i in b if i in self.entities for t in self.entities[i]["tags"]}
        shared = sorted(ta & tb)
        return {"success": True, "results": {"tags": [
            {"tag_id": t, "name": self.tags[t]["name"], "shared": True} for t in shared]}}


class _HTTP(Exception):
    def __init__(self, status: int, msg: str):
        self.status, self.msg = status, msg
