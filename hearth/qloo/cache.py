"""Private on-disk response cache.

Qloo allows private server-side caching but response data must never be put
in a public repository. The default cache dir (.cache/qloo) is gitignored.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


class DiskCache:
    def __init__(self, directory: str | os.PathLike[str], ttl_seconds: float | None = 7 * 24 * 3600):
        self.dir = Path(directory)
        self.ttl = ttl_seconds

    @staticmethod
    def key(path: str, params: list[tuple[str, str]]) -> str:
        raw = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params))
        return hashlib.sha256(raw.encode()).hexdigest()

    def _file(self, key: str) -> Path:
        return self.dir / key[:2] / f"{key}.json"

    def get(self, key: str) -> Any | None:
        f = self._file(key)
        if not f.exists():
            return None
        if self.ttl is not None and time.time() - f.stat().st_mtime > self.ttl:
            return None
        try:
            return json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def set(self, key: str, value: Any) -> None:
        f = self._file(key)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(value))
        tmp.replace(f)
