"""Hearth HTTP API (FastAPI) + the built web app.

Run:  HEARTH_MOCK=1 uvicorn hearth.api:app --reload

The JSON API lives under /api. When web/dist exists (``cd web && npm run build``)
the single-page app is served at / from the same process.

Each browser keeps its own care home: it sends a random ``X-Hearth-Home`` id
(no account, no personal data). Requests without it use the "default" home.
"""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .constraints import entity_filter
from .demo import DEMO_CITY, DEMO_HOME, resolve_demo
from .feedback import apply_feedback
from .models import ERA_MAX_YEAR, ERA_MIN_YEAR, EntityRef, EraMode, Need, Profile, Tag
from .planner import GroupPick, WeeklyPlan, group_pick, weekly_plan
from .qloo import QlooClient, QlooError, QlooParamError
from .ratelimit import RateLimiter, buckets_for
from .storage import Store
from .verifier import Candidate, Resolution, VerifyReport, domain_to_type, resolve, verify
from .verifier.core import _tag_rank


class EntityIn(BaseModel):
    id: str = Field(max_length=100)
    name: str = Field(max_length=200)
    type: str = Field(max_length=40)
    tags: list[Tag] = Field(default_factory=list, max_length=40)
    year: int | None = Field(default=None, ge=1800, le=2100,
                             description="Release year (films/TV); sets the resident's automatic era")

    def to_ref(self, etype: str) -> EntityRef:
        props = {"release_year": self.year} if self.year is not None else {}
        return EntityRef(id=self.id, name=self.name, type=etype, tags=self.tags, properties=props)


class EraIn(BaseModel):
    """Film/TV era (a Hearth setting): auto = newest favourite + 10 years; year = set; off = no limit."""
    era_mode: EraMode = "auto"
    era_max_year: int | None = Field(default=None, ge=ERA_MIN_YEAR, le=ERA_MAX_YEAR)


class ResidentIn(EraIn):
    name: str = Field(min_length=1, max_length=80, description="Display name only (first name or initials)")
    entities: list[EntityIn] = Field(default_factory=list, max_length=30,
                                     description="Confirmed Qloo entities they like")
    tags: list[Tag] = Field(default_factory=list, max_length=30, description="Confirmed Qloo tag ids")
    needs: list[Need] = Field(default_factory=list)


class VerifyIn(BaseModel):
    resident_id: str | None = None
    profile: Profile | None = None
    candidates: list[Candidate] = Field(min_length=1, max_length=25)
    # Place picks are compared with what Qloo ranks for this person in this locality (e.g. "London").
    place_location: str | None = Field(default=None, max_length=100)


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


class HomeIn(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80, description="Town used to find local outings")


MAX_RESIDENTS = int(os.environ.get("HEARTH_MAX_RESIDENTS_PER_HOME", "12"))
DIST = Path(os.environ.get("HEARTH_WEB_DIST") or Path(__file__).resolve().parent.parent / "web" / "dist")
_HOME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DOMAIN_LABEL = {"artist": "music", "movie": "film", "tv_show": "tv", "place": "place"}


def _image_url(props: dict[str, Any]) -> str | None:
    img = props.get("image")
    if isinstance(img, dict):
        return img.get("url")
    return img if isinstance(img, str) else None


def _walk_images(obj: Any, out: dict[str, str]) -> None:
    """Collect entity id -> image url from any response (kept in memory only, never written)."""
    if isinstance(obj, dict):
        props = obj.get("properties")
        if isinstance(props, dict) and obj.get("id") and (url := _image_url(props)):
            out[str(obj["id"])] = url
        for v in obj.values():
            _walk_images(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_images(v, out)


def _display_tags(e: EntityRef, n: int = 3) -> list[str]:
    seen, out = set(), []
    for t in sorted(e.tags, key=lambda t: _tag_rank(t.id)):
        if t.name and t.name.lower() not in seen and ":obscurity:" not in t.id:
            seen.add(t.name.lower())
            out.append(t.name)
    return out[:n]


def _keep_year(e: EntityRef) -> dict[str, Any]:
    """The only Qloo property stored with a favourite: its release year (sets the automatic era)."""
    y = e.properties.get("release_year")
    return {"release_year": y} if y is not None else {}


def _era_or_422(mode: str, year: int | None) -> int | None:
    if mode == "year" and year is None:
        raise HTTPException(422, "era_max_year is required when era_mode is 'year'")
    return year if mode == "year" else None


def create_app(client: QlooClient | None = None, db_path: str | None = None,
               web_dist: Path | None = None, rate_limiter: RateLimiter | None | bool = True,
               max_residents: int | None = None) -> FastAPI:
    """``rate_limiter``: True = from env (default), False/None = off, or a RateLimiter."""
    limiter = RateLimiter.from_env() if rate_limiter is True else (rate_limiter or None)
    cap = MAX_RESIDENTS if max_residents is None else max_residents
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.qloo = client or QlooClient()
        app.state.store = Store(db_path or os.environ.get("HEARTH_DB", "hearth.db"))
        app.state.images = {}       # entity id -> Qloo image url, in memory only
        app.state.demo = None       # resolved demo favourites (process cache)
        app.state.demo_lock = asyncio.Lock()
        try:
            yield
        finally:
            await app.state.qloo.aclose()
            app.state.store.close()

    app = FastAPI(title="Hearth", version=__version__, lifespan=lifespan,
                  description="Taste-aware care coordinator for older adults. Taste from Qloo; "
                              "care rules are Hearth's. JSON API under /api.")
    api = APIRouter(prefix="/api")

    if limiter is not None:
        @app.middleware("http")
        async def _rate_limit(request: Request, call_next):
            buckets = buckets_for(request.method, request.url.path)
            if buckets:
                ip = request.client.host if request.client else "unknown"
                ok, retry, bucket = limiter.check(ip, buckets)
                if not ok:
                    return JSONResponse(
                        status_code=429, headers={"Retry-After": str(retry)},
                        content={"detail": f"Too many requests ({bucket}); this public demo is rate limited. "
                                           f"Try again in {retry} s."})
            return await call_next(request)

    def _store(req: Request) -> Store:
        return req.app.state.store

    def _qloo(req: Request) -> QlooClient:
        return req.app.state.qloo

    def _home(req: Request) -> str:
        h = req.headers.get("x-hearth-home", "")
        return h if _HOME_RE.match(h) else "default"

    def _profile(req: Request, rid: str) -> Profile:
        p = _store(req).get_profile(rid)
        if p is None or _store(req).home_of(rid) != _home(req):
            raise HTTPException(404, f"resident {rid} not found")
        return p

    def _domain(domain: str) -> str:
        try:
            return domain_to_type(domain)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    def _place_extra(req: Request) -> dict | None:
        city = _store(req).get_home(_home(req))["city"]
        return {"filter.location.query": city} if city else None

    def _remember(req: Request, model: BaseModel | list) -> None:
        data = [m.model_dump() for m in model] if isinstance(model, list) else model.model_dump()
        _walk_images(data, req.app.state.images)

    async def _with_images(req: Request, profiles: list[Profile]) -> list[Profile]:
        """Attach favourite photos (Qloo image urls) at response time; the DB never stores them."""
        images: dict[str, str] = req.app.state.images
        missing = {e.id: e for p in profiles for e in p.entities if e.id not in images and e.weight > 0}

        async def look(e: EntityRef) -> None:
            try:
                for r in await _qloo(req).search(e.name, types=[e.type], take=5):
                    if (url := _image_url(r.properties)):
                        images.setdefault(r.id, url)
            except QlooError:
                return
        if missing:
            await asyncio.gather(*(look(e) for e in list(missing.values())[:24]))
        for p in profiles:
            for e in p.entities:
                if e.id in images:
                    e.properties["image"] = {"url": images[e.id]}
        return profiles

    @app.exception_handler(QlooParamError)
    async def _param_err(_: Request, exc: QlooParamError):
        return JSONResponse(status_code=422, content={"detail": f"invalid Qloo parameters: {exc}"})

    @app.exception_handler(QlooError)
    async def _qloo_err(_: Request, exc: QlooError):
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @api.get("/health")
    async def health(req: Request) -> JSONResponse:
        """Liveness for the deploy check: process up and the database answering. No Qloo call."""
        try:
            _store(req).count_residents("default")
            db = True
        except Exception:  # noqa: BLE001 - report, don't crash the probe
            db = False
        return JSONResponse(status_code=200 if db else 503,
                            content={"ok": db, "db": db, "version": __version__, "mock": _qloo(req).mock,
                                     "rate_limited": limiter is not None, "max_residents_per_home": cap})

    # ---- the care home (this browser's) ------------------------------------
    @api.get("/home")
    async def get_home(req: Request) -> dict[str, Any]:
        home = _store(req).get_home(_home(req))
        return {**home, "residents": len(_store(req).list_residents(_home(req))), "mock": _qloo(req).mock}

    @api.put("/home")
    async def put_home(req: Request, body: HomeIn) -> dict[str, Any]:
        return _store(req).set_home(_home(req), name=body.name, city=body.city)

    @api.delete("/home")
    async def delete_home(req: Request) -> dict[str, Any]:
        """Erase this home: every resident, their favourites, needs and feedback."""
        return {"deleted_residents": _store(req).delete_home(_home(req))}

    @api.post("/demo")
    async def seed_demo(req: Request) -> dict[str, Any]:
        """Load the sample home "Maple House" (4 residents). Favourites are resolved live by name."""
        store, home = _store(req), _home(req)
        existing = store.list_residents(home)
        if store.get_home(home)["demo"] and existing:
            return {"home": store.get_home(home), "created": 0}
        async with req.app.state.demo_lock:
            if req.app.state.demo is None:
                req.app.state.demo = await resolve_demo(_qloo(req))
        room = cap - len(existing)
        if room < len(req.app.state.demo):
            raise HTTPException(409, f"This home has {len(existing)} residents; the sample home needs room for "
                                     f"{len(req.app.state.demo)} (limit {cap} per home). Remove some first.")
        created = 0
        for persona, ents in req.app.state.demo:
            for e in ents:
                if (url := _image_url(e.properties)):
                    req.app.state.images[e.id] = url
            store.create_resident(persona.name, [e.model_copy(update={"properties": _keep_year(e)}) for e in ents],
                                  [], list(persona.needs), home_id=home)
            created += 1
        return {"home": store.set_home(home, name=DEMO_HOME, city=DEMO_CITY, demo=True), "created": created}

    # ---- looking things up ---------------------------------------------------
    @api.get("/search")
    async def search(req: Request, q: str = Query(min_length=1, max_length=100), domain: str = "artist",
                     take: int = Query(default=6, ge=1, le=10)) -> dict[str, Any]:
        """Qloo /search for the setup flow: photo cards to confirm a favourite."""
        etype = _domain(domain)
        results = [r for r in await _qloo(req).search(q, types=[etype], take=take) if r.type == etype]
        out = []
        for r in results:
            if (url := _image_url(r.properties)):
                req.app.state.images[r.id] = url
            year = r.properties.get("release_year") or r.properties.get("publication_year")
            out.append({"id": r.id, "name": r.name, "type": r.type, "image": _image_url(r.properties),
                        "year": year, "disambiguation": r.properties.get("disambiguation"),
                        "popularity": r.properties.get("popularity"), "display_tags": _display_tags(r),
                        "tags": [t.model_dump() for t in r.tags[:12]]})
        return {"query": q, "domain": domain, "results": out}

    @api.get("/resolve", response_model=Resolution)
    async def resolve_name(req: Request, name: str, domain: str) -> Resolution:
        """Look up a free-text favourite so staff can confirm the right Qloo entity."""
        _domain(domain)
        res = await resolve(_qloo(req), Candidate(name=name, domain=domain))
        _remember(req, res)
        return res

    # ---- residents -----------------------------------------------------------
    @api.get("/residents", response_model=list[Profile])
    async def list_residents(req: Request) -> list[Profile]:
        return await _with_images(req, _store(req).list_residents(_home(req)))

    @api.post("/residents", response_model=Profile, status_code=201)
    async def create_resident(req: Request, body: ResidentIn) -> Profile:
        if _store(req).count_residents(_home(req)) >= cap:
            raise HTTPException(409, f"This home already has {cap} residents, the limit for this demo. "
                                     "Remove one to add another.")
        year = _era_or_422(body.era_mode, body.era_max_year)
        ents = [e.to_ref(_domain(e.type)) for e in body.entities]
        return _store(req).create_resident(body.name, ents, body.tags, body.needs, home_id=_home(req),
                                           era_mode=body.era_mode, era_max_year=year)

    @api.put("/residents/{rid}/era", response_model=Profile)
    async def set_era(req: Request, rid: str, body: EraIn) -> Profile:
        """Film/TV era for picks and swaps (a Hearth setting, not Qloo)."""
        _profile(req, rid)
        _store(req).set_era(rid, body.era_mode, _era_or_422(body.era_mode, body.era_max_year))
        return (await _with_images(req, [_profile(req, rid)]))[0]

    @api.get("/residents/{rid}", response_model=Profile)
    async def get_resident(req: Request, rid: str) -> Profile:
        return (await _with_images(req, [_profile(req, rid)]))[0]

    @api.delete("/residents/{rid}", status_code=204)
    async def delete_resident(req: Request, rid: str) -> Response:
        """Remove a resident and everything Hearth stored about them."""
        _profile(req, rid)
        _store(req).delete_resident(rid)
        return Response(status_code=204)

    @api.get("/residents/{rid}/history")
    async def history(req: Request, rid: str) -> list[dict[str, Any]]:
        _profile(req, rid)
        return _store(req).history(rid)

    @api.post("/verify", response_model=VerifyReport)
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
        loc = body.place_location
        extra = {"place": {"filter.location.query": loc}} if loc else (
            {"place": pe} if (pe := _place_extra(req)) else None)
        rep = await verify(_qloo(req), prof, body.candidates, swap_filter=swap_ok, ranked_extra=extra)
        _remember(req, rep)
        return rep

    @api.get("/residents/{rid}/plan", response_model=WeeklyPlan)
    async def plan(req: Request, rid: str, skip: list[str] = Query(default=[]),
                   skip_cuisine: list[str] = Query(default=[])) -> WeeklyPlan:
        """Weekly plan. ``skip`` (entity ids) and ``skip_cuisine`` swap picks for the next best."""
        wp = await weekly_plan(_qloo(req), _profile(req, rid), facts=_store(req).all_facts(),
                               place_extra=_place_extra(req), skip_ids=skip, skip_cuisines=skip_cuisine)
        _remember(req, wp)
        return wp

    @api.post("/group-pick", response_model=GroupPick)
    async def group(req: Request, body: GroupPickIn) -> GroupPick:
        _domain(body.domain)
        profiles = [_profile(req, rid) for rid in dict.fromkeys(body.resident_ids)]
        gp = await group_pick(_qloo(req), profiles, body.domain, candidates=body.candidates,
                              facts=_store(req).all_facts(), place_extra=_place_extra(req))
        _remember(req, gp)
        return gp

    @api.post("/feedback", response_model=Profile)
    async def feedback(req: Request, body: FeedbackIn) -> Profile:
        prof = _profile(req, body.resident_id)
        ent = body.entity.to_ref(_domain(body.entity.type))
        updated = apply_feedback(prof, ent, body.enjoyed)
        _store(req).save_profile(updated)
        _store(req).log_feedback(body.resident_id, ent.id, body.enjoyed)
        return _profile(req, body.resident_id)

    @api.put("/venues/{entity_id}/facts")
    async def put_facts(req: Request, entity_id: str, body: FactsIn) -> dict[str, Any]:
        return {"entity_id": entity_id, "facts": _store(req).set_facts(entity_id, body.model_dump()),
                "label": "Hearth data, not Qloo"}

    app.include_router(api)

    # ---- the web app (single process) -------------------------------------------
    dist = Path(web_dist) if web_dist else DIST
    index = dist / "index.html"
    if index.exists():
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "not found")
            f = (dist / path).resolve()
            if path and f.is_file() and dist.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
