"""LLM interface stub. No provider is wired yet (choice pending).

Hearth's core never needs an LLM: the verifier, rules and planner are
deterministic. An LLM may later (a) draft candidate picks that the verifier
then checks, and (b) phrase evidence for staff. Whatever it writes is checked
or labelled; it is never the source of a taste or care judgement.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import Profile
from .verifier.models import Candidate, CheckResult


@runtime_checkable
class LLMProvider(Protocol):
    async def draft_candidates(self, profile: Profile, domain: str, n: int = 5) -> list[Candidate]:
        """Propose free-text picks for a domain. Output goes to verifier.verify()."""
        ...

    async def explain(self, result: CheckResult) -> str:
        """Plain-language explanation of a verdict, from its evidence only."""
        ...


class NoLLM:
    """Default: no provider configured."""

    async def draft_candidates(self, profile: Profile, domain: str, n: int = 5) -> list[Candidate]:
        raise NotImplementedError("no LLM provider configured (set one up in hearth/llm.py)")

    async def explain(self, result: CheckResult) -> str:
        ev = result.evidence
        tags = ", ".join(t.name for t in ev.shared_tags) or "no shared tags"
        return f"{result.candidate.name}: {result.verdict.value} (relative fit {ev.relative_fit}; {tags})"
