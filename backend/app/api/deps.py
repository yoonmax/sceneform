"""Request dependencies: anonymous ownership, project access, rate limiting."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Query, Request

from ..config import settings
from ..storage.db import db, row_dict
from ..storage.files import hash_owner, valid_owner_token, verify

_buckets: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def rate_limit(key: str, per_minute: int | None = None) -> None:
    limit = per_minute or settings.rate_limit_per_minute
    t = time.time()
    with _lock:
        q = _buckets[key]
        while q and t - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, "You're making requests too quickly. Please wait a moment.")
        q.append(t)


def owner(request: Request, x_sceneform_owner: str | None = Header(default=None)) -> str:
    """Anonymous owner identity: a random token kept in the browser.

    Only its hash is stored. Every project query is filtered by it, so one
    visitor can never list or open another visitor's projects.
    """
    if not valid_owner_token(x_sceneform_owner):
        raise HTTPException(401, "Missing or invalid owner token.")
    h = hash_owner(x_sceneform_owner)
    rate_limit(h)
    return h


def owned_project(project_id: str, owner_hash: str) -> dict:
    row = db().execute("SELECT * FROM projects WHERE id=? AND owner=?", (project_id, owner_hash)).fetchone()
    if row is None:
        # Same response for "missing" and "not yours" — ids are not oracles.
        raise HTTPException(404, "Project not found.")
    return row_dict(row)


def signed_project(project_id: str, sig: str | None = Query(default=None),
                   x_sceneform_owner: str | None = Header(default=None)) -> dict:
    """Access for asset URLs (images, binaries) that can't carry headers."""
    if sig and verify(project_id, sig):
        row = db().execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row:
            return row_dict(row)
    if valid_owner_token(x_sceneform_owner):
        return owned_project(project_id, hash_owner(x_sceneform_owner))
    raise HTTPException(404, "Not found.")
