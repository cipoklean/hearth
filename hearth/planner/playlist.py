"""Personal playlist: the resident's own favourite artists, then the artists Qloo ranks highest for
their whole taste profile, each with the reason Qloo gives. Care rules (e.g. mild content) and staff
feedback apply. Deterministic for the same profile and Qloo answers."""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..constraints.rules import unasked_dark
from ..models import EntityRef, Profile, Tag
from ..qloo import QlooClient
from ..verifier import top_for
from ..verifier.core import (affinity_of, leading_favourite, relative_fit, shared_tags,
                             signal_contributions)

ARTIST = "urn:entity:artist"


class PlaylistItem(BaseModel):
    entity: EntityRef
    source: str  # "favourite" (staff/family entered) or "qloo" (ranked for this profile)
    relative_fit: float | None = None
    reason: str
    shared_tags: list[Tag] = Field(default_factory=list)


class Playlist(BaseModel):
    resident_id: str | None
    name: str
    items: list[PlaylistItem]
    source_note: str = ("Favourites come from staff and family. New artists are ranked by Qloo's taste graph "
                        "for this resident's whole profile; Hearth removes anything marked not enjoyed.")


async def playlist(client: QlooClient, profile: Profile, *, take: int = 12) -> Playlist:
    items: list[PlaylistItem] = []
    for e in profile.entities:
        if e.type == ARTIST and e.id not in profile.disliked:
            items.append(PlaylistItem(entity=e, source="favourite", reason="one of their favourites"))
    ranked = await top_for(client, profile, ARTIST, take=30) if profile.entities else []
    best = max([affinity_of(e) for e in ranked] or [0.0])
    have = {i.entity.id for i in items}
    for e in ranked:
        if len(items) >= take:
            break
        if e.id in have or e.id in profile.disliked or unasked_dark(e, profile):
            continue
        tags = shared_tags(e, profile)
        lead = leading_favourite(signal_contributions(e, profile))
        parts = []
        if lead:
            parts.append(f"Qloo links it most to {lead.name}")
        if tags:
            parts.append("shares " + ", ".join(t.name for t in tags[:2]))
        items.append(PlaylistItem(entity=e, source="qloo", relative_fit=relative_fit(affinity_of(e), best),
                                  reason="; ".join(parts) or "ranked high by Qloo for their taste",
                                  shared_tags=tags))
        have.add(e.id)
    return Playlist(resident_id=profile.resident_id, name=profile.name, items=items)
