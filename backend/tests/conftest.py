import os
import secrets

import pytest


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    from app.config import settings
    from app.storage import db as dbmod

    monkeypatch.setattr(settings, "data_dir", tmp_path / "var")
    settings.data_dir.mkdir(parents=True)
    dbmod._local.__dict__.clear()
    dbmod.init()
    yield settings.data_dir
    dbmod._local.__dict__.clear()


@pytest.fixture()
def client(data_dir, monkeypatch):
    monkeypatch.setenv("SCENEFORM_DISABLE_WORKER", "1")
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def owner_headers():
    return {"X-Sceneform-Owner": secrets.token_hex(24)}
