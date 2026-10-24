"""Shared data models. Hearth stores only confirmed Qloo IDs, names and needs."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Tag(BaseModel):
    id: str
    name: str = ""
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


class Profile(BaseModel):
    """A person's taste profile: confirmed Qloo entity IDs + tags, plus needs."""
    resident_id: str | None = None
    name: str = ""
    entities: list[EntityRef] = Field(default_factory=list)
    tags: list[Tag] = Field(default_factory=list)
    disliked: list[str] = Field(default_factory=list)  # entity ids
    needs: list[Need] = Field(default_factory=list)

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
