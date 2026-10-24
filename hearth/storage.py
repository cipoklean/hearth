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
CREATE TABLE IF NOT EXISTS homes (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  city TEXT NOT NULL DEFAULT '',
  demo INTEGER NOT NULL DEFAULT 0
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
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(residents)")}
        if "home_id" not in cols:  # older DBs: one implicit home
            self._conn.execute("ALTER TABLE residents ADD COLUMN home_id TEXT NOT NULL DEFAULT 'default'")
            self._conn.commit()
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    # ---- residents -----------------------------------------------------------
    def create_resident(self, name: str, entities: list[EntityRef], tags: list[Tag],
                        needs: list[Need], home_id: str = "default") -> Profile:
        rid = uuid.uuid4().hex[:12]
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO residents (id, name, needs, home_id) VALUES (?, ?, ?, ?)",
                               (rid, name, json.dumps([n.value for n in needs]), home_id))
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

    def home_of(self, rid: str) -> str | None:
        row = self._conn.execute("SELECT home_id FROM residents WHERE id = ?", (rid,)).fetchone()
        return row["home_id"] if row else None

    def list_residents(self, home_id: str = "default") -> list[Profile]:
        rows = self._conn.execute("SELECT id FROM residents WHERE home_id = ? ORDER BY rowid", (home_id,))
        return [p for r in rows.fetchall() if (p := self.get_profile(r["id"])) is not None]

    def delete_resident(self, rid: str) -> bool:
        """Remove a resident and everything stored about them (favourites, tags, feedback)."""
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM residents WHERE id = ?", (rid,))
            # explicit, in case foreign keys were off when rows were written
            for t in ("resident_entities", "resident_tags", "feedback"):
                self._conn.execute(f"DELETE FROM {t} WHERE resident_id = ?", (rid,))
        return cur.rowcount > 0

    def history(self, rid: str) -> list[dict[str, Any]]:
        """Feedback log, newest first, with the entity name kept in the profile."""
        q = ("SELECT f.entity_id, f.enjoyed, f.created_at, e.name, e.type FROM feedback f "
             "LEFT JOIN resident_entities e ON e.resident_id = f.resident_id AND e.entity_id = f.entity_id "
             "WHERE f.resident_id = ? ORDER BY f.id DESC LIMIT 50")
        return [{"entity_id": r["entity_id"], "name": r["name"] or "", "type": r["type"] or "",
                 "enjoyed": bool(r["enjoyed"]), "created_at": r["created_at"]}
                for r in self._conn.execute(q, (rid,))]

    # ---- homes (a name and town per browser; no personal data) ---------------
    def get_home(self, home_id: str) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM homes WHERE id = ?", (home_id,)).fetchone()
        if row is None:
            return {"id": home_id, "name": "", "city": "", "demo": False}
        return {"id": row["id"], "name": row["name"], "city": row["city"], "demo": bool(row["demo"])}

    def set_home(self, home_id: str, name: str | None = None, city: str | None = None,
                 demo: bool | None = None) -> dict[str, Any]:
        cur = self.get_home(home_id)
        new = {"name": cur["name"] if name is None else name, "city": cur["city"] if city is None else city,
               "demo": cur["demo"] if demo is None else demo}
        with self._lock, self._conn:
            self._conn.execute("INSERT OR REPLACE INTO homes (id, name, city, demo) VALUES (?,?,?,?)",
                               (home_id, new["name"], new["city"], int(new["demo"])))
        return self.get_home(home_id)

    def delete_home(self, home_id: str) -> int:
        ids = [r["id"] for r in self._conn.execute("SELECT id FROM residents WHERE home_id = ?", (home_id,))]
        for rid in ids:
            self.delete_resident(rid)
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM homes WHERE id = ?", (home_id,))
        return len(ids)

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
