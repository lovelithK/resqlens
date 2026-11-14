"""Environment-based configuration.

Values come from environment variables or a ``.env`` file (project root
``.env`` or ``backend/.env``). Nothing secret is hard-coded or sent to the
frontend. See ``.env.example`` for every supported variable.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from .database import DatabaseConfig

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
PROJECT_ROOT = BASE_DIR.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines); real environment variables win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")
_load_dotenv(PROJECT_ROOT / ".env")


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n)
        if v not in (None, ""):
            return v
    return default


def _resolve(path: str) -> str:
    """Relative SQLite paths are resolved against the backend/ folder."""
    if path == ":memory:" or os.path.isabs(path):
        return path
    return str(BASE_DIR / path)


def _database_config() -> DatabaseConfig:
    engine = _env("DB_ENGINE", "RESQ_DB_ENGINE", default="sqlite").lower()
    if engine not in ("sqlite", "mysql"):
        raise RuntimeError(f"DB_ENGINE must be 'sqlite' or 'mysql', got '{engine}'")
    return DatabaseConfig(
        engine=engine,
        path=_resolve(_env("RESQ_DATABASE_PATH", "SQLITE_PATH", default="resqlens.db")),
        host=_env("DB_HOST", default="127.0.0.1"),
        port=int(_env("DB_PORT", default="3306")),
        name=_env("DB_NAME", default="resqlens_db"),
        user=_env("DB_USER", default="resqlens_app"),
        password=_env("DB_PASSWORD"),
        ssl=_env("DB_SSL", default="0") == "1",
        ssl_ca=_env("DB_SSL_CA"),
    )


def _cors() -> tuple[str, ...]:
    raw = _env("CORS_ORIGINS", "RESQ_CORS_ORIGINS",
               default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    frontend = _env("FRONTEND_URL")
    if frontend and frontend not in origins:
        origins.append(frontend)
    return tuple(origins)


@dataclass(frozen=True)
class Settings:
    app_env: str = field(default_factory=lambda: _env("APP_ENV", default="development"))
    database: DatabaseConfig = field(default_factory=_database_config)
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", "RESQ_SECRET_KEY"))
    token_ttl_minutes: int = field(default_factory=lambda: int(_env("TOKEN_TTL_MINUTES", "RESQ_TOKEN_TTL_MINUTES", default="720")))
    cors_origins: tuple[str, ...] = field(default_factory=_cors)
    frontend_dist: str = field(default_factory=lambda: _env("RESQ_FRONTEND_DIST", default=str(PROJECT_ROOT / "frontend" / "dist")))
    seed_demo: bool = field(default_factory=lambda: _env("SEED_DEMO", "RESQ_SEED_DEMO", default="1") == "1")
    debug: bool = field(default_factory=lambda: _env("DEBUG", "RESQ_DEBUG", default="0") == "1")

    @property
    def database_path(self) -> str:  # backwards compatibility
        return self.database.path


def get_settings() -> Settings:
    settings = Settings()
    if not settings.secret_key:
        if settings.app_env == "production":
            raise RuntimeError("SECRET_KEY must be set in production")
        # Development fallback: a per-process random key (sessions end on restart).
        os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
        settings = Settings()
    return settings
