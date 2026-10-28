"""Per-IP rate limits for a public demo (in memory, per process).

Three buckets, each "N requests per W seconds" per client IP:

  qloo    routes that may call Qloo: search, resolve, verify, plan, group pick, demo seeding,
          and resident reads (favourite photos are looked up on a cache miss)
  create  creating residents and seeding the sample home
  api     everything else under /api (a generous ceiling)

/api/health and the static web app are never limited. Behind a reverse proxy, run uvicorn with
``--proxy-headers --forwarded-allow-ips=127.0.0.1`` so ``request.client`` is the real visitor.
Counters live in each worker process, so with N workers the effective ceiling is up to N x.

Configure with env vars, e.g. ``HEARTH_RATE_QLOO=30/60``; ``HEARTH_RATE_LIMIT=0`` turns it off.
"""
from __future__ import annotations

import math
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

DEFAULTS = {"qloo": "30/60", "create": "20/3600", "api": "240/60"}

_QLOO_ROUTES = (
    ("GET", re.compile(r"^/api/search$")),
    ("GET", re.compile(r"^/api/resolve$")),
    ("POST", re.compile(r"^/api/verify$")),
    ("GET", re.compile(r"^/api/residents/[^/]+/plan$")),
    ("POST", re.compile(r"^/api/group-pick$")),
    ("POST", re.compile(r"^/api/demo$")),
    ("GET", re.compile(r"^/api/residents(/[^/]+)?$")),
)
_CREATE_ROUTES = (
    ("POST", re.compile(r"^/api/residents$")),
    ("POST", re.compile(r"^/api/demo$")),
)
EXEMPT = ("/api/health",)


@dataclass(frozen=True)
class Limit:
    count: int
    window: float

    @classmethod
    def parse(cls, spec: str) -> "Limit":
        m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+(?:\.\d+)?)\s*", spec or "")
        if not m or int(m.group(1)) < 1 or float(m.group(2)) <= 0:
            raise ValueError(f"rate limit must look like 30/60 (requests/seconds), got {spec!r}")
        return cls(int(m.group(1)), float(m.group(2)))


def buckets_for(method: str, path: str) -> list[str]:
    """Which buckets a request counts against (empty = not limited)."""
    if path == "/mcp" and method == "POST":
        return ["api", "qloo"]  # every MCP call may reach Qloo
    if not path.startswith("/api/") or path in EXEMPT:
        return []
    out = ["api"]
    if any(m == method and r.match(path) for m, r in _QLOO_ROUTES):
        out.append("qloo")
    if any(m == method and r.match(path) for m, r in _CREATE_ROUTES):
        out.append("create")
    return out


class RateLimiter:
    """Sliding-window counters keyed by (bucket, ip). Thread-safe; ``clock`` is injectable for tests."""

    def __init__(self, limits: dict[str, Limit], clock: Callable[[], float] = time.monotonic,
                 max_keys: int = 50_000):
        self.limits = limits
        self.clock = clock
        self.max_keys = max_keys
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "RateLimiter | None":
        env = dict(os.environ if env is None else env)
        if env.get("HEARTH_RATE_LIMIT", "1").strip().lower() in {"0", "off", "false", "no"}:
            return None
        return cls({b: Limit.parse(env.get(f"HEARTH_RATE_{b.upper()}", d)) for b, d in DEFAULTS.items()})

    def check(self, ip: str, buckets: list[str]) -> tuple[bool, int, str | None]:
        """Record a hit. Returns (allowed, retry_after_seconds, bucket that refused)."""
        now = self.clock()
        with self._lock:
            if len(self._hits) > self.max_keys:
                self._prune(now)
            for b in buckets:  # refuse without recording if any bucket is full
                lim = self.limits[b]
                q = self._hits.get((b, ip))
                if q is None:
                    continue
                while q and q[0] <= now - lim.window:
                    q.popleft()
                if len(q) >= lim.count:
                    return False, max(1, math.ceil(q[0] + lim.window - now)), b
            for b in buckets:
                self._hits.setdefault((b, ip), deque()).append(now)
        return True, 0, None

    def _prune(self, now: float) -> None:
        for key in list(self._hits):
            q = self._hits[key]
            win = self.limits[key[0]].window
            while q and q[0] <= now - win:
                q.popleft()
            if not q:
                del self._hits[key]
