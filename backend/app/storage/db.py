"""SQLite persistence (metadata only — media lives on disk, never in rows)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from ..config import settings

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    expires_at REAL,
    status TEXT NOT NULL DEFAULT 'draft',
    input_type TEXT,
    settings TEXT NOT NULL DEFAULT '{}',
    quality TEXT,
    latest_run TEXT,
    thumbnail TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS projects_owner ON projects(owner);
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    width INTEGER, height INTEGER, duration REAL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS assets_project ON assets(project_id);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    owner TEXT NOT NULL,
    run_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    state TEXT NOT NULL,
    stage TEXT,
    stage_label TEXT,
    progress REAL,
    message TEXT,
    error TEXT,
    error_code TEXT,
    config TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    heartbeat_at REAL,
    pid INTEGER
);
CREATE INDEX IF NOT EXISTS jobs_project ON jobs(project_id);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id TEXT,
    mode TEXT NOT NULL,
    created_at REAL NOT NULL,
    summary TEXT,
    edits TEXT NOT NULL DEFAULT '{"version":1,"ops":[]}'
);
CREATE INDEX IF NOT EXISTS runs_project ON runs(project_id);
"""

_local = threading.local()


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def init(path: Path | None = None) -> None:
    con = connect(path)
    con.executescript(SCHEMA)
    row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if row is None:
        con.execute("INSERT INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
    con.close()


def db() -> sqlite3.Connection:
    """Per-thread connection (cheap, avoids cross-thread sharing)."""
    key = str(settings.db_path)
    cache = getattr(_local, "cons", None)
    if cache is None:
        cache = _local.cons = {}
    if key not in cache:
        cache[key] = connect()
    return cache[key]


@contextmanager
def tx():
    con = db()
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def row_dict(row: sqlite3.Row | None, json_fields=("settings", "quality", "config", "summary", "edits")) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in json_fields:
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except json.JSONDecodeError:
                pass
    return d


def now() -> float:
    return time.time()
