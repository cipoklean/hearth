"""Feedback loop: staff mark an activity enjoyed / not enjoyed -> profile weights change.

Pure function; the API persists the result. Weights are Hearth's, not Qloo's:
they decide which confirmed entities are sent to Qloo as signals.
"""
from __future__ import annotations

from .models import EntityRef, Profile

ENJOYED_STEP = 0.5
NOT_ENJOYED_STEP = 1.0
TAG_STEP = 0.25
MAX_WEIGHT = 3.0


def apply_feedback(profile: Profile, entity: EntityRef, enjoyed: bool) -> Profile:
    p = profile.model_copy(deep=True)
    current = next((e for e in p.entities if e.id == entity.id), None)
    tag_ids = {t.id for t in entity.tags}
    if enjoyed:
        p.disliked = [d for d in p.disliked if d != entity.id]
        if current is None:
            p.entities.append(entity.model_copy(update={"weight": 1.0}))
        else:
            current.weight = min(MAX_WEIGHT, max(current.weight, 0.0) + ENJOYED_STEP)
        for t in p.tags:
            if t.id in tag_ids:
                t.weight = min(MAX_WEIGHT, t.weight + TAG_STEP)
    else:
        if current is None:
            # never liked and not enjoyed: remember it so it is not suggested again
            p.entities.append(entity.model_copy(update={"weight": -1.0}))
            p.disliked.append(entity.id)
        else:
            # a liked item first drops to neutral (no longer a signal), then to disliked
            current.weight = max(-1.0, current.weight - NOT_ENJOYED_STEP)
            if current.weight < 0 and entity.id not in p.disliked:
                p.disliked.append(entity.id)
        for t in p.tags:
            if t.id in tag_ids:
                t.weight = max(0.0, t.weight - TAG_STEP)
    return p
