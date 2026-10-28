"""Hearth as an agent tool: a Model Context Protocol (MCP) server at POST /mcp.

Any MCP client (Claude, Cursor, an OpenAI Agents SDK app, a care-home's own agent) can call
Hearth's taste check before it recommends anything to an older person. The agent describes
the person by favourite names and care needs; Hearth resolves the names to Qloo entities,
measures fit on Qloo's taste graph, applies its care rules and returns verdicts with evidence.

Transport: MCP "Streamable HTTP", answered as single JSON responses (no server push, no
session state). Stateless and anonymous: nothing an agent sends here is stored.

    {"mcpServers": {"hearth": {"url": "https://<host>/mcp"}}}
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from . import __version__
from .constraints import entity_filter
from .demo import resolve_favourite
from .models import EntityRef, Need, Profile
from .planner import group_pick, weekly_plan
from .qloo import QlooClient, QlooError
from .verifier import Candidate, domain_to_type, resolve, verify

log = logging.getLogger(__name__)

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DOMAINS = ["artist", "movie", "tv_show", "book", "place", "destination", "podcast", "video_game", "brand"]
NEEDS = [n.value for n in Need]
MAX_FAVOURITES, MAX_CANDIDATES, MAX_PEOPLE = 12, 15, 8

INSTRUCTIONS = (
    "Hearth checks recommendations for older adults against their real cultural taste (Qloo's taste graph) "
    "and their care needs (Hearth's rules). Before you suggest films, music, meals or outings to an older "
    "person, call check_picks with their favourites and your ideas, and use the verdicts and swaps. "
    "'Can't verify' means Qloo could not identify the title: do not present it as a confident pick. "
    "Care rules are guidance for staff, not medical advice.")


# ---- tool inputs -------------------------------------------------------------------
class Item(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: str = Field(description="artist, movie, tv_show, book, place, destination, podcast, video_game, brand")


class Person(BaseModel):
    name: str = Field(default="Resident", max_length=80)
    favourites: list[Item] = Field(min_length=1, max_length=MAX_FAVOURITES)
    needs: list[Need] = Field(default_factory=list)


class CheckIn(Person):
    candidates: list[Item] = Field(min_length=1, max_length=MAX_CANDIDATES)
    town: str | None = Field(default=None, max_length=120)


class PlanIn(Person):
    town: str | None = Field(default=None, max_length=120)


class GroupIn(BaseModel):
    people: list[Person] = Field(min_length=1, max_length=MAX_PEOPLE)
    domain: str = "movie"
    candidates: list[Item] | None = Field(default=None, max_length=MAX_CANDIDATES)
    town: str | None = Field(default=None, max_length=120)


class FindIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: str


def _item_schema() -> dict:
    return {"type": "object", "required": ["name", "domain"],
            "properties": {"name": {"type": "string"}, "domain": {"type": "string", "enum": DOMAINS}}}


def _person_props() -> dict:
    return {
        "name": {"type": "string", "description": "First name or label (not stored)"},
        "favourites": {"type": "array", "items": _item_schema(), "minItems": 1, "maxItems": MAX_FAVOURITES,
                       "description": "Things the person already loves, by name, e.g. Frank Sinatra (artist), "
                                      "Casablanca (movie)"},
        "needs": {"type": "array", "items": {"type": "string", "enum": NEEDS},
                  "description": "Care needs, checked by Hearth's rules (not Qloo)"},
    }


TOOLS: list[dict[str, Any]] = [
    {
        "name": "check_picks",
        "title": "Check recommendations against a person's taste",
        "description": "Verify ideas (films, music, places...) for an older adult. Each idea gets a verdict "
                       "(good / weak / poor fit, cannot_verify, or ambiguous) measured on Qloo's taste graph from "
                       "the person's favourites, the evidence behind it, care-rule results, and a better-fitting "
                       "swap that passes their care needs. Call this before presenting recommendations.",
        "inputSchema": {"type": "object", "required": ["favourites", "candidates"], "properties": {
            **_person_props(),
            "candidates": {"type": "array", "items": _item_schema(), "minItems": 1, "maxItems": MAX_CANDIDATES,
                           "description": "The ideas to check"},
            "town": {"type": "string", "description": "Town for place ideas, e.g. 'Bath, UK'"}}},
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "plan_week",
        "title": "Plan a week of activities",
        "description": "A week plan for one older adult: two lunch themes with care-safe dishes, a music "
                       "session, a film night and an outing, each picked from Qloo's taste graph and checked "
                       "against their care needs, with evidence.",
        "inputSchema": {"type": "object", "required": ["favourites"], "properties": {
            **_person_props(), "town": {"type": "string", "description": "Town for meals and outings"}}},
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "group_pick",
        "title": "Pick one activity for a group",
        "description": "The best shared film, artist or outing for several people, with a fit score per person, "
                       "an alternative for anyone it leaves out, and options set aside by care rules. Pass "
                       "candidates to choose among your own ideas, or leave them out to let Hearth suggest.",
        "inputSchema": {"type": "object", "required": ["people"], "properties": {
            "people": {"type": "array", "minItems": 1, "maxItems": MAX_PEOPLE,
                       "items": {"type": "object", "required": ["favourites"], "properties": _person_props()}},
            "domain": {"type": "string", "enum": DOMAINS, "default": "movie"},
            "candidates": {"type": "array", "items": _item_schema(), "maxItems": MAX_CANDIDATES},
            "town": {"type": "string"}}},
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "find_entity",
        "title": "Look up a title or name in Qloo",
        "description": "Resolve a name to a Qloo entity. Returns resolved, ambiguous (with options) or "
                       "cannot_verify. Useful to confirm a favourite before checking picks.",
        "inputSchema": {"type": "object", "required": ["name", "domain"], "properties": {
            "name": {"type": "string"}, "domain": {"type": "string", "enum": DOMAINS}}},
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
]


class ToolError(Exception):
    """Reported to the agent as a tool result with isError (not a protocol error)."""


def _check_domain(domain: str) -> str:
    try:
        return domain_to_type(domain)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


async def _profile(client: QlooClient, person: Person) -> tuple[Profile, list[str]]:
    for f in person.favourites:
        _check_domain(f.domain)
    found = await asyncio.gather(*(resolve_favourite(client, f.domain, f.name, None) for f in person.favourites))
    ents: list[EntityRef] = []
    missing: list[str] = []
    for f, e in zip(person.favourites, found):
        if e is None:
            missing.append(f"{f.name} ({f.domain})")
        elif all(x.id != e.id for x in ents):
            ents.append(e)
    if not ents:
        raise ToolError("Qloo couldn't identify any of the favourites, so there is no taste to measure against. "
                        "Use exact titles or names (find_entity helps).")
    return Profile(name=person.name, entities=ents, needs=list(dict.fromkeys(person.needs))), missing


def _place(town: str | None) -> dict | None:
    return {"filter.location.query": town} if town else None


def _brief(e: EntityRef | None) -> dict | None:
    if e is None:
        return None
    y = e.properties.get("release_year")
    return {"name": e.name, "qloo_id": e.id, "type": e.type.rsplit(":", 1)[-1], **({"year": y} if y else {})}


def _favs_note(p: Profile, missing: list[str]) -> dict:
    return {"favourites_used": [_brief(e) for e in p.entities], "favourites_not_found": missing}


async def call_tool(client: QlooClient, facts: dict, name: str, args: dict) -> dict:
    try:
        if name == "check_picks":
            inp = CheckIn.model_validate(args)
            for c in inp.candidates:
                _check_domain(c.domain)
            prof, missing = await _profile(client, inp)
            swap_ok = entity_filter(prof.needs, facts) if prof.needs else None
            extra = {"place": pl} if (pl := _place(inp.town)) else None
            rep = await verify(client, prof, [Candidate(name=c.name, domain=c.domain) for c in inp.candidates],
                               swap_filter=swap_ok, ranked_extra=extra)
            return {**_favs_note(prof, missing), **rep.model_dump(mode="json")}
        if name == "plan_week":
            inp = PlanIn.model_validate(args)
            prof, missing = await _profile(client, inp)
            wp = await weekly_plan(client, prof, facts=facts, place_extra=_place(inp.town))
            return {**_favs_note(prof, missing), **wp.model_dump(mode="json")}
        if name == "group_pick":
            inp = GroupIn.model_validate(args)
            _check_domain(inp.domain)
            built = [await _profile(client, p) for p in inp.people]
            for i, (p, _) in enumerate(built):
                p.resident_id = f"p{i + 1}"
            cands = [Candidate(name=c.name, domain=c.domain) for c in inp.candidates] if inp.candidates else None
            gp = await group_pick(client, [p for p, _ in built], inp.domain, candidates=cands, facts=facts,
                                  place_extra=_place(inp.town))
            return {"people": [{"name": p.name, **_favs_note(p, m)} for p, m in built],
                    **gp.model_dump(mode="json")}
        if name == "find_entity":
            inp = FindIn.model_validate(args)
            _check_domain(inp.domain)
            return (await resolve(client, Candidate(name=inp.name, domain=inp.domain))).model_dump(mode="json")
    except ValidationError as exc:
        raise ToolError("Invalid arguments: " + "; ".join(
            f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])) from exc
    except QlooError as exc:
        raise ToolError(f"Qloo request failed ({exc.status}); try again shortly") from exc
    raise ToolError(f"Unknown tool: {name}")


# ---- JSON-RPC over Streamable HTTP ---------------------------------------------------------
def _ok(rid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


async def handle(app: FastAPI, msg: Any) -> dict | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _err(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
    rid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if "id" not in msg:  # notification (e.g. notifications/initialized): no response
        return None
    if method == "initialize":
        asked = params.get("protocolVersion")
        return _ok(rid, {
            "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "hearth", "title": "Hearth taste check", "version": __version__},
            "instructions": INSTRUCTIONS})
    if method == "ping":
        return _ok(rid, {})
    if method == "tools/list":
        return _ok(rid, {"tools": TOOLS})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if not isinstance(args, dict):
            return _err(rid, -32602, "arguments must be an object")
        try:
            data = await call_tool(app.state.qloo, app.state.store.all_facts(), str(name), args)
        except ToolError as exc:
            return _ok(rid, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
        except Exception:  # noqa: BLE001 - never leak internals to a public endpoint
            log.exception("mcp tool %s failed", name)
            return _ok(rid, {"content": [{"type": "text", "text": "Hearth hit an internal error"}],
                             "isError": True})
        return _ok(rid, {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                         "structuredContent": data, "isError": False})
    return _err(rid, -32601, f"Method not found: {method}")


def mount(app: FastAPI) -> None:
    @app.post("/mcp", include_in_schema=False)
    async def mcp_post(req: Request) -> Response:
        try:
            body = await req.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse(_err(None, -32700, "Parse error"), status_code=400)
        if isinstance(body, list):  # batch (older protocol versions)
            out = [r for r in [await handle(app, m) for m in body[:20]] if r is not None]
            return JSONResponse(out) if out else Response(status_code=202)
        res = await handle(app, body)
        return JSONResponse(res) if res is not None else Response(status_code=202)

    @app.get("/mcp", include_in_schema=False)
    async def mcp_get() -> Response:
        # No server-initiated stream: this server only answers requests.
        return Response(status_code=405, headers={"Allow": "POST"})

    @app.delete("/mcp", include_in_schema=False)
    async def mcp_delete() -> Response:
        return Response(status_code=405, headers={"Allow": "POST"})
