"""Hearth HTTP API (FastAPI).

Run:  HEARTH_MOCK=1 uvicorn hearth.api:app --reload
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import __version__
from .constraints import entity_filter
from .feedback import apply_feedback
from .models import EntityRef, Need, Profile, Tag
from .planner import GroupPick, WeeklyPlan, group_pick, weekly_plan
from .qloo import QlooClient, QlooError, QlooParamError
from .storage import Store
from .verifier import Candidate, Resolution, VerifyReport, domain_to_type, resolve, verify


class EntityIn(BaseModel):
    id: str
    name: str
    type: str
    tags: list[Tag] = Field(default_factory=list)


class ResidentIn(BaseModel):
    name: str = Field(min_length=1, max_length=80, description="Display name only (first name or initials)")
    entities: list[EntityIn] = Field(default_factory=list, description="Confirmed Qloo entities they like")
    tags: list[Tag] = Field(default_factory=list, description="Confirmed Qloo tag ids")
    needs: list[Need] = Field(default_factory=list)


class VerifyIn(BaseModel):
    resident_id: str | None = None
    profile: Profile | None = None
    candidates: list[Candidate] = Field(min_length=1, max_length=25)


class GroupPickIn(BaseModel):
    resident_ids: list[str] = Field(min_length=1, max_length=30)
    domain: str
    candidates: list[Candidate] | None = None


class FeedbackIn(BaseModel):
    resident_id: str
    entity: EntityIn
    enjoyed: bool


class FactsIn(BaseModel):
    """Staff-entered venue/film facts used by Hearth rules (not Qloo)."""
    step_free: bool | None = None
    quiet: bool | None = None
    subtitles: bool | None = None
    soft_food_options: bool | None = None
    low_salt_options: bool | None = None
    low_sugar_options: bool | None = None
    vegetarian_options: bool | None = None


def create_app(client: QlooClient | None = None, db_path: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.qloo = client or QlooClient()
        app.state.store = Store(db_path or os.environ.get("HEARTH_DB", "hearth.db"))
        try:
            yield
        finally:
            await app.state.qloo.aclose()
            app.state.store.close()

    app = FastAPI(title="Hearth", version=__version__, lifespan=lifespan,
                  description="Taste-aware care coordinator for older adults. Taste from Qloo; "
                              "care rules are Hearth's.")

    def _store(req: Request) -> Store:
        return req.app.state.store

    def _qloo(req: Request) -> QlooClient:
        return req.app.state.qloo

    def _profile(req: Request, rid: str) -> Profile:
        p = _store(req).get_profile(rid)
        if p is None:
            raise HTTPException(404, f"resident {rid} not found")
        return p

    def _domain(domain: str) -> str:
        try:
            return domain_to_type(domain)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.exception_handler(QlooParamError)
    async def _param_err(_: Request, exc: QlooParamError):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=422, content={"detail": f"invalid Qloo parameters: {exc}"})

    @app.exception_handler(QlooError)
    async def _qloo_err(_: Request, exc: QlooError):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.get("/health")
    async def health(req: Request) -> dict[str, Any]:
        return {"ok": True, "version": __version__, "mock": _qloo(req).mock}

    @app.get("/resolve", response_model=Resolution)
    async def resolve_name(req: Request, name: str, domain: str) -> Resolution:
        """Look up a free-text favourite so staff can confirm the right Qloo entity."""
        _domain(domain)
        return await resolve(_qloo(req), Candidate(name=name, domain=domain))

    @app.post("/residents", response_model=Profile, status_code=201)
    async def create_resident(req: Request, body: ResidentIn) -> Profile:
        ents = [EntityRef(id=e.id, name=e.name, type=_domain(e.type), tags=e.tags) for e in body.entities]
        return _store(req).create_resident(body.name, ents, body.tags, body.needs)

    @app.get("/residents/{rid}", response_model=Profile)
    async def get_resident(req: Request, rid: str) -> Profile:
        return _profile(req, rid)

    @app.post("/verify", response_model=VerifyReport)
    async def verify_route(req: Request, body: VerifyIn) -> VerifyReport:
        if body.resident_id:
            prof = _profile(req, body.resident_id)
        elif body.profile:
            prof = body.profile
        else:
            raise HTTPException(422, "give resident_id or profile")
        for c in body.candidates:
            _domain(c.domain)
        swap_ok = entity_filter(prof.needs, _store(req).all_facts()) if prof.needs else None
        return await verify(_qloo(req), prof, body.candidates, swap_filter=swap_ok)

    @app.get("/residents/{rid}/plan", response_model=WeeklyPlan)
    async def plan(req: Request, rid: str) -> WeeklyPlan:
        return await weekly_plan(_qloo(req), _profile(req, rid), facts=_store(req).all_facts())

    @app.post("/group-pick", response_model=GroupPick)
    async def group(req: Request, body: GroupPickIn) -> GroupPick:
        _domain(body.domain)
        profiles = [_profile(req, rid) for rid in dict.fromkeys(body.resident_ids)]
        return await group_pick(_qloo(req), profiles, body.domain, candidates=body.candidates,
                                facts=_store(req).all_facts())

    @app.post("/feedback", response_model=Profile)
    async def feedback(req: Request, body: FeedbackIn) -> Profile:
        prof = _profile(req, body.resident_id)
        ent = EntityRef(id=body.entity.id, name=body.entity.name, type=_domain(body.entity.type),
                        tags=body.entity.tags)
        updated = apply_feedback(prof, ent, body.enjoyed)
        _store(req).save_profile(updated)
        _store(req).log_feedback(body.resident_id, ent.id, body.enjoyed)
        return _profile(req, body.resident_id)

    @app.put("/venues/{entity_id}/facts")
    async def put_facts(req: Request, entity_id: str, body: FactsIn) -> dict[str, Any]:
        return {"entity_id": entity_id, "facts": _store(req).set_facts(entity_id, body.model_dump()),
                "label": "Hearth data, not Qloo"}

    return app


app = create_app()
