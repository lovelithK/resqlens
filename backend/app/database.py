"""Database access layer over the Python DB-API, supporting two engines:

* **SQLite** (zero-config default; used by the automated test-suite)
* **MySQL 8** via PyMySQL (the recommended local / production database)

Every query is written once with ``?`` placeholders and parameterised – user
input is never interpolated into SQL, which prevents SQL injection. For MySQL
the placeholders are translated to ``%s`` and column names are back-quoted, so
reserved words such as ``key`` and ``trigger`` work on both engines.
``Database.transaction()`` gives one connection per unit of work and commits or
rolls back atomically.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

SQLITE_SCHEMA = Path(__file__).with_name("schema.sql")
MYSQL_SCHEMA = Path(__file__).with_name("schema_mysql.sql")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dumps(value: Any) -> str:
    return json.dumps(value, default=str)


def loads(value: str | None, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    return json.loads(value)


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


@dataclass(frozen=True)
class DatabaseConfig:
    engine: str = "sqlite"            # "sqlite" | "mysql"
    path: str = "resqlens.db"         # sqlite file
    host: str = "127.0.0.1"
    port: int = 3306
    name: str = "resqlens_db"
    user: str = ""
    password: str = ""
    ssl: bool = False                 # TLS to the MySQL server (required by most hosted MySQL services)
    ssl_ca: str = ""                  # optional CA bundle path; system CAs are used when empty

    def describe(self) -> str:
        """Human-readable target without the password (safe for logs)."""
        if self.engine == "mysql":
            return f"mysql://{self.user}@{self.host}:{self.port}/{self.name}"
        return f"sqlite:///{self.path}"


def _plain(value: Any) -> Any:
    # MySQL returns DECIMAL for SUM()/AVG(); JSON cannot serialise Decimal.
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


class Connection:
    """Engine-neutral wrapper with small helper methods."""

    def __init__(self, raw: Any, dialect: str):
        self._raw = raw
        self.dialect = dialect

    # -- dialect helpers ------------------------------------------------------
    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.dialect == "mysql" else sql

    def group_concat(self, column: str, sep: str = ", ") -> str:
        if self.dialect == "mysql":
            return f"GROUP_CONCAT({column} SEPARATOR '{sep}')"
        return f"group_concat({column}, '{sep}')"

    # -- query API ----------------------------------------------------------------
    def execute(self, sql: str, params: tuple | list = ()):
        if self.dialect == "mysql":
            cur = self._raw.cursor()
            cur.execute(self._sql(sql), tuple(params))
            return cur
        return self._raw.execute(sql, params)

    def _rows(self, cur) -> list[dict]:
        rows = cur.fetchall()
        if self.dialect == "mysql":
            rows = [{k: _plain(v) for k, v in r.items()} for r in rows]
        return list(rows)

    def one(self, sql: str, params: tuple | list = ()) -> dict | None:
        rows = self._rows(self.execute(sql, params))
        return rows[0] if rows else None

    def all(self, sql: str, params: tuple | list = ()) -> list[dict]:
        return self._rows(self.execute(sql, params))

    def scalar(self, sql: str, params: tuple | list = ()) -> Any:
        row = self.one(sql, params)
        if row is None:
            return None
        return next(iter(row.values()))

    def insert(self, table: str, values: dict) -> int:
        cols = ", ".join(f"`{k}`" for k in values.keys())
        marks = ", ".join("?" for _ in values)
        cur = self.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values()))
        return int(cur.lastrowid)

    def update(self, table: str, row_id: int, values: dict) -> None:
        if not values:
            return
        sets = ", ".join(f"`{k}` = ?" for k in values)
        self.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*values.values(), row_id))

    def executescript(self, script: str) -> None:
        if self.dialect == "sqlite":
            self._raw.executescript(script)
            return
        # strip comments, split on ';' (the MySQL schema contains no procedures)
        cleaned = re.sub(r"--[^\n]*", "", script)
        for stmt in cleaned.split(";"):
            if stmt.strip():
                self.execute(stmt)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()


class Database:
    def __init__(self, target: str | DatabaseConfig):
        self.config = target if isinstance(target, DatabaseConfig) else DatabaseConfig(engine="sqlite", path=target)
        if self.config.engine == "sqlite" and self.config.path != ":memory:":
            Path(self.config.path).parent.mkdir(parents=True, exist_ok=True)

    # kept for backwards compatibility (tests / scripts use .path)
    @property
    def path(self) -> str:
        return self.config.path

    @property
    def dialect(self) -> str:
        return self.config.engine

    def connect(self) -> Connection:
        cfg = self.config
        if cfg.engine == "mysql":
            try:
                import pymysql
                from pymysql.cursors import DictCursor
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise RuntimeError("PyMySQL is required for MySQL: pip install -r requirements.txt") from exc
            tls = None
            if cfg.ssl:
                import ssl as _ssl
                tls = _ssl.create_default_context(cafile=cfg.ssl_ca or None)
            raw = pymysql.connect(host=cfg.host, port=cfg.port, user=cfg.user, password=cfg.password,
                                  database=cfg.name, charset="utf8mb4", cursorclass=DictCursor,
                                  autocommit=False, connect_timeout=10, ssl=tls)
            return Connection(raw, "mysql")
        raw = sqlite3.connect(cfg.path, check_same_thread=False, timeout=15)
        raw.row_factory = _dict_factory
        raw.execute("PRAGMA foreign_keys = ON")
        raw.execute("PRAGMA journal_mode = WAL")
        return Connection(raw, "sqlite")

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        schema = MYSQL_SCHEMA if self.dialect == "mysql" else SQLITE_SCHEMA
        with self.transaction() as conn:
            conn.executescript(schema.read_text(encoding="utf-8"))

    def check(self) -> dict:
        """Connectivity probe used by /api/health."""
        with self.transaction() as conn:
            version = conn.scalar("SELECT VERSION()" if self.dialect == "mysql" else "SELECT sqlite_version()")
            tables = conn.scalar("SELECT COUNT(*) FROM users")
        return {"engine": self.dialect, "version": version, "users": tables}
