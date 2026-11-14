"""ASGI application entry point.

Run:  uvicorn app.main:app --reload --host 127.0.0.1 --port 8000   (from the backend/ folder)
API docs: http://localhost:8000/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .api.openapi import openapi_routes
from .api.routes import register
from .api.routing import Api
from .config import get_settings
from .database import Database, DatabaseConfig
from .repositories import RecoveryRepository
from .services.recovery import strategy_rows

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("resqlens")

_state: dict = {}


def ensure_reference_data(db: Database) -> None:
    with db.transaction() as conn:
        RecoveryRepository(conn).ensure_strategies(strategy_rows())


def create_app(database: str | DatabaseConfig | None = None, seed_demo: bool | None = None) -> Starlette:
    """``database``: a SQLite file path, an explicit DatabaseConfig, or None to use .env settings."""
    settings = get_settings()
    if isinstance(database, DatabaseConfig):
        db = Database(database)
    else:
        db = Database(DatabaseConfig(engine="sqlite", path=database) if database else settings.database)
    _state["db"] = db
    _state["settings"] = settings

    @asynccontextmanager
    async def lifespan(app):
        log.info("Environment: %s | database: %s", settings.app_env, db.config.describe())
        try:
            db.initialize()
        except Exception as exc:
            log.error("Cannot initialise the database (%s): %s", db.config.describe(), exc)
            if db.dialect == "mysql":
                log.error("Check that MySQL Server is running, the database '%s' exists and DB_USER/DB_PASSWORD "
                          "in .env are correct. See docs/TROUBLESHOOTING.md.", db.config.name)
            raise
        ensure_reference_data(db)
        if settings.seed_demo if seed_demo is None else seed_demo:
            from .seed import ensure_demo_user
            ensure_demo_user(db)
        yield

    api = Api(lambda: db, lambda: settings)
    register(api, lambda: settings)

    routes = list(api.routes) + openapi_routes(api)
    dist = Path(settings.frontend_dist)
    if (dist / "index.html").exists():
        if (dist / "assets").exists():
            routes.append(Mount("/assets", app=StaticFiles(directory=dist / "assets"), name="assets"))

        async def spa(request: Request):
            path = request.path_params.get("path", "")
            if path.startswith("api/") or path in ("docs", "openapi.json"):
                return JSONResponse({"error": {"code": "NOT_FOUND", "message": "Unknown API endpoint"}}, 404)
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

        routes.append(Route("/{path:path}", spa, methods=["GET"]))

    middleware = [Middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=True,
                             allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])]
    return Starlette(debug=settings.debug, routes=routes, middleware=middleware, lifespan=lifespan)


app = create_app()
