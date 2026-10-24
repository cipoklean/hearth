"""Shared data models. Hearth stores only confirmed Qloo IDs, names and needs."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field


class Tag(BaseModel):
    id: str
    name: str = ""
    type: str = ""  # e.g. urn:tag:genre:music (Qloo); empty when unknown
    weight: float = 1.0


class EntityRef(BaseModel):
    """A Qloo entity the user has confirmed (or one returned by Qloo)."""
    id: str
    name: str
    type: str  # urn:entity:*
    tags: list[Tag] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    weight: float = 1.0  # Hearth feedback weight (not Qloo)


class Need(str, Enum):
    """Health/care needs. Evaluated by Hearth rules, never by Qloo."""
    soft_food = "soft_food"
    low_salt = "low_salt"
    low_sugar = "low_sugar"
    vegetarian = "vegetarian"
    wheelchair_access = "wheelchair_access"
    quiet_setting = "quiet_setting"
    hearing_support = "hearing_support"
    short_duration = "short_duration"
    mild_content = "mild_content"


# ---- era (a Hearth setting, not Qloo) -------------------------------------------
# Live picks lean towards acclaimed modern films (plan/calibration.md). For older adults Hearth
# limits film and TV picks/swaps to an "era": a latest release year, set by staff or derived
# from the resident's favourite films/shows (newest favourite + ERA_MARGIN years).
ERA_TYPES = ("urn:entity:movie", "urn:entity:tv_show")
ERA_MARGIN = 10
ERA_MIN_YEAR = 1900
ERA_MAX_YEAR = 2100
EraMode = Literal["auto", "year", "off"]


class Era(BaseModel):
    max_year: int
    source: Literal["auto", "set"]
    explanation: str
    label: str = "Era: Hearth setting"


class Profile(BaseModel):
    """A person's taste profile: confirmed Qloo entity IDs + tags, plus needs."""
    resident_id: str | None = None
    name: str = ""
    entities: list[EntityRef] = Field(default_factory=list)
    tags: list[Tag] = Field(default_factory=list)
    disliked: list[str] = Field(default_factory=list)  # entity ids
    needs: list[Need] = Field(default_factory=list)
    # auto: derive from favourites; year: era_max_year as set by staff; off: no era limit
    era_mode: EraMode = "auto"
    era_max_year: int | None = Field(default=None, ge=ERA_MIN_YEAR, le=ERA_MAX_YEAR)

    def favourite_years(self) -> list[int]:
        """Release years of liked favourite films/shows (stored with the favourite)."""
        out = []
        for e in self.entities:
            if e.type in ERA_TYPES and e.weight > 0 and e.id not in self.disliked:
                y = e.properties.get("release_year")
                if isinstance(y, (int, float)) and ERA_MIN_YEAR <= int(y) <= ERA_MAX_YEAR:
                    out.append(int(y))
        return out

    @computed_field  # type: ignore[prop-decorator]
    @property
    def era(self) -> Era | None:
        """The era limit in force for film/TV picks, or None for no limit."""
        if self.era_mode == "off":
            return None
        if self.era_mode == "year" and self.era_max_year:
            return Era(max_year=self.era_max_year, source="set",
                       explanation=f"films and TV up to {self.era_max_year}, set by staff")
        years = self.favourite_years()
        if not years:
            return None
        newest = max(years)
        return Era(max_year=newest + ERA_MARGIN, source="auto",
                   explanation=f"films and TV up to {newest + ERA_MARGIN} (newest favourite {newest} "
                               f"+ {ERA_MARGIN} years)")

    def signal_entity_ids(self) -> list[str]:
        """Entities used as Qloo signals: positive weight, not disliked, stable order."""
        bad = set(self.disliked)
        ents = [e for e in self.entities if e.weight > 0 and e.id not in bad]
        ents.sort(key=lambda e: (-e.weight, e.id))
        return [e.id for e in ents]

    def signal_tag_ids(self) -> list[str]:
        tags = [t for t in self.tags if t.weight > 0]
        tags.sort(key=lambda t: (-t.weight, t.id))
        return [t.id for t in tags]

    def known_tags(self) -> dict[str, str]:
        """tag id -> name over profile tags and tags of liked entities."""
        out: dict[str, str] = {}
        for t in self.tags:
            if t.weight > 0:
                out[t.id] = t.name or t.id
        for e in self.entities:
            if e.weight > 0 and e.id not in self.disliked:
                for t in e.tags:
                    out.setdefault(t.id, t.name or t.id)
        return out
