"""On-disk layout, ownership, signed URLs, and retention.

Layout (never exposed directly):

    <data>/projects/<project_id>/inputs/<random>.<ext>
    <data>/projects/<project_id>/runs/<run_id>/{work,outputs,exports}/

Project ids are 128-bit random; every request must also present the owner
token (hashed server-side) or a short-lived HMAC signature scoped to one
project, so knowing an id alone grants nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import shutil
import time
from pathlib import Path

from ..config import settings


def new_id(nbytes: int = 16) -> str:
    return secrets.token_hex(nbytes)


def hash_owner(token: str) -> str:
    return hashlib.sha256(("sceneform-owner:" + token).encode()).hexdigest()


def valid_owner_token(token: str | None) -> bool:
    return bool(token) and 32 <= len(token) <= 128 and all(c in "0123456789abcdefABCDEF-_" for c in token)


def _secret() -> bytes:
    path = settings.data_dir / ".signing_key"
    env = os.environ.get("SCENEFORM_SIGNING_KEY")
    if env:
        return env.encode()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_hex(32))
    return path.read_text().strip().encode()


def sign(project_id: str, ttl_seconds: int = 6 * 3600) -> str:
    exp = int(time.time()) + ttl_seconds
    mac = hmac.new(_secret(), f"{project_id}:{exp}".encode(), hashlib.sha256).hexdigest()[:40]
    return f"{exp}.{mac}"


def verify(project_id: str, sig: str | None) -> bool:
    if not sig or "." not in sig:
        return False
    exp_s, mac = sig.split(".", 1)
    if not exp_s.isdigit() or int(exp_s) < time.time():
        return False
    good = hmac.new(_secret(), f"{project_id}:{exp_s}".encode(), hashlib.sha256).hexdigest()[:40]
    return hmac.compare_digest(good, mac)


def project_dir(project_id: str) -> Path:
    if not project_id or not all(c in "0123456789abcdef" for c in project_id):
        raise ValueError("bad project id")
    return settings.projects_dir / project_id


def run_dir(project_id: str, run_id: str) -> Path:
    if not all(c in "0123456789abcdef" for c in run_id):
        raise ValueError("bad run id")
    return project_dir(project_id) / "runs" / run_id


def safe_join(base: Path, rel: str) -> Path:
    """Resolve ``rel`` under ``base`` and refuse anything escaping it."""
    base = base.resolve()
    target = (base / rel).resolve()
    if base != target and base not in target.parents:
        raise PermissionError("path escapes base directory")
    return target


def delete_project_files(project_id: str) -> None:
    d = project_dir(project_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0
