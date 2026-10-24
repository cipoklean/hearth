"""SQLite storage. Minimal personal data by design.

Stored per resident: a display name, needs, confirmed Qloo entity/tag IDs (with
the names and tags needed to show evidence), and feedback weights. No dates of
birth, room numbers, medical records or free-text notes. The DB file is
private (gitignored), like the Qloo cache.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from typing import Any

from .models import EntityRef, Need, Profile, Tag

SCHEMA = """
CREATE TABLE IF NOT EXISTS residents (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  needs TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS resident_entities (
  resident_id TEXT NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
  entity_id TEXT NOT NULL,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',
  weight REAL NOT NULL DEFAULT 1.0,
  disliked INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (resident_id, entity_id)
);
CREATE TABLE IF NOT EXISTS resident_tags (
  resident_id TEXT NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
  tag_id TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  weight REAL NOT NULL DEFAULT 1.0,
  PRIMARY KEY (resident_id, tag_id)
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  resident_id TEXT NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
  entity_id TEXT NOT NULL,
  enjoyed INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS venue_facts (
  entity_id TEXT PRIMARY KEY,
  facts TEXT NOT NULL DEFAULT '{}'
);
"""


class Store:
    def __init__(self, path: str = "hearth.db"):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    # ---- residents -----------------------------------------------------------
    def create_resident(self, name: str, entities: list[EntityRef], tags: list[Tag],
                        needs: list[Need]) -> Profile:
        rid = uuid.uuid4().hex[:12]
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO residents (id, name, needs) VALUES (?, ?, ?)",
                               (rid, name, json.dumps([n.value for n in needs])))
            for e in entities:
                self._upsert_entity(rid, e, e.weight, False)
            for t in tags:
                self._conn.execute(
                    "INSERT OR REPLACE INTO resident_tags (resident_id, tag_id, name, weight) VALUES (?,?,?,?)",
                    (rid, t.id, t.name, t.weight))
        prof = self.get_profile(rid)
        assert prof is not None
        return prof

    def _upsert_entity(self, rid: str, e: EntityRef, weight: float, disliked: bool) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO resident_entities (resident_id, entity_id, name, type, tags, weight, disliked)"
            " VALUES (?,?,?,?,?,?,?)",
            (rid, e.id, e.name, e.type, json.dumps([t.model_dump() for t in e.tags]), weight, int(disliked)))

    def get_profile(self, rid: str) -> Profile | None:
        row = self._conn.execute("SELECT * FROM residents WHERE id = ?", (rid,)).fetchone()
        if row is None:
            return None
        ents, disliked = [], []
        for r in self._conn.execute(
                "SELECT * FROM resident_entities WHERE resident_id = ? ORDER BY entity_id", (rid,)):
            if r["disliked"]:
                disliked.append(r["entity_id"])
            ents.append(EntityRef(id=r["entity_id"], name=r["name"], type=r["type"],
                                  tags=[Tag(**t) for t in json.loads(r["tags"])], weight=r["weight"]))
        tags = [Tag(id=r["tag_id"], name=r["name"], weight=r["weight"]) for r in self._conn.execute(
            "SELECT * FROM resident_tags WHERE resident_id = ? ORDER BY tag_id", (rid,))]
        return Profile(resident_id=rid, name=row["name"], entities=ents, tags=tags, disliked=disliked,
                       needs=[Need(n) for n in json.loads(row["needs"])])

    def save_profile(self, p: Profile) -> None:
        assert p.resident_id
        with self._lock, self._conn:
            self._conn.execute("UPDATE residents SET name = ?, needs = ? WHERE id = ?",
                               (p.name, json.dumps([n.value for n in p.needs]), p.resident_id))
            self._conn.execute("DELETE FROM resident_entities WHERE resident_id = ?", (p.resident_id,))
            for e in p.entities:
                self._upsert_entity(p.resident_id, e, e.weight, e.id in p.disliked)
            self._conn.execute("DELETE FROM resident_tags WHERE resident_id = ?", (p.resident_id,))
            for t in p.tags:
                self._conn.execute(
                    "INSERT INTO resident_tags (resident_id, tag_id, name, weight) VALUES (?,?,?,?)",
                    (p.resident_id, t.id, t.name, t.weight))

    def log_feedback(self, rid: str, entity_id: str, enjoyed: bool) -> None:
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO feedback (resident_id, entity_id, enjoyed) VALUES (?,?,?)",
                               (rid, entity_id, int(enjoyed)))

    # ---- venue facts (staff-entered, Hearth data) ------------------------------
    def set_facts(self, entity_id: str, facts: dict[str, Any]) -> dict[str, Any]:
        merged = {**self.get_facts(entity_id), **{k: v for k, v in facts.items() if v is not None}}
        with self._lock, self._conn:
            self._conn.execute("INSERT OR REPLACE INTO venue_facts (entity_id, facts) VALUES (?, ?)",
                               (entity_id, json.dumps(merged)))
        return merged

    def get_facts(self, entity_id: str) -> dict[str, Any]:
        row = self._conn.execute("SELECT facts FROM venue_facts WHERE entity_id = ?", (entity_id,)).fetchone()
        return json.loads(row["facts"]) if row else {}

    def all_facts(self) -> dict[str, dict[str, Any]]:
        return {r["entity_id"]: json.loads(r["facts"])
                for r in self._conn.execute("SELECT * FROM venue_facts")}
