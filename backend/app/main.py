"""sceneform API server.

    uvicorn app.main:app --port 8000

The vision pipeline lives in ``app.pipeline`` and never imports FastAPI; this
module only wires HTTP routes, the job supervisor and housekeeping.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import exports, projects, reconstruction, uploads
from .config import settings
from .pipeline.runner import PIPELINE_VERSION
from .storage import db as dbmod
from .workers.worker import Supervisor

supervisor: Supervisor | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global supervisor
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(settings.data_dir, 0o700)
    dbmod.init()
    if os.environ.get("SCENEFORM_DISABLE_WORKER") != "1":
        supervisor = Supervisor()
        supervisor.start()
    yield
    if supervisor:
        supervisor.stop()


app = FastAPI(title="sceneform", version=PIPELINE_VERSION, lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-Sceneform-Owner"],
    max_age=600,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


@app.exception_handler(ValueError)
async def value_error(_: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)[:300]})


@app.get("/api/health")
def health():
    return {"ok": True, "service": "sceneform", "version": PIPELINE_VERSION}


app.include_router(reconstruction.router)
app.include_router(projects.router)
app.include_router(uploads.router)
app.include_router(exports.router)
