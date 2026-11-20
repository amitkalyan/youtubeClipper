"""Local API. One process, one worker, bound to localhost."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import db
from app.api.routes import health, jobs, projects
from app.config import get_settings
from app.errors import (
    ClipperError,
    FFmpegNotFoundError,
    JobBusyError,
    NotFoundError,
    UploadTooLargeError,
)
from app.logging_config import configure_logging
from app.services.job_manager import job_manager

logger = logging.getLogger("clipper.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    configure_logging(settings.data_dir / "logs" / "app.log")
    db.init_db()
    db.fail_interrupted_jobs()
    job_manager.start()
    logger.info("Clipper API ready data_dir=%s", settings.data_dir)
    try:
        yield
    finally:
        job_manager.shutdown()
        db.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")

    @app.get("/")
    def root() -> dict:
        return {"service": "clipper", "phase": 4, "docs": "/docs"}

    @app.exception_handler(ClipperError)
    async def handle_clipper_error(request: Request, exc: ClipperError) -> JSONResponse:
        status = _status_for(exc)
        logger.info("%s %s -> %s %s", request.method, request.url.path, status, exc)
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return app


def _status_for(exc: ClipperError) -> int:
    if isinstance(exc, JobBusyError):
        return 409
    if isinstance(exc, UploadTooLargeError):
        return 413
    if isinstance(exc, FFmpegNotFoundError):
        return 503
    if isinstance(exc, NotFoundError):
        return 404
    return 400


app = create_app()
