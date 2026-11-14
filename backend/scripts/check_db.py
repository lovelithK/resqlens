"""Database connectivity check for ResQLens.

Run from the backend folder (virtual environment active):
    python -m scripts.check_db

It verifies, using the settings in .env: authentication, database availability,
schema creation (idempotent), a read, a write and a transaction rollback.
The password is never printed.
"""
from __future__ import annotations

import sys
import uuid

from app.config import get_settings
from app.database import Database, utcnow


def main() -> int:
    settings = get_settings()
    db = Database(settings.database)
    print(f"Target   : {db.config.describe()}")
    steps = []

    def step(name, fn):
        try:
            detail = fn()
            steps.append((name, True, detail))
            print(f"  [ OK ] {name}: {detail}")
            return True
        except Exception as exc:  # report and stop
            steps.append((name, False, str(exc)))
            print(f"  [FAIL] {name}: {exc}")
            return False

    def connect():
        conn = db.connect()
        version = conn.scalar("SELECT VERSION()" if db.dialect == "mysql" else "SELECT sqlite_version()")
        conn.close()
        return f"connected, server version {version}"

    def schema():
        db.initialize()
        with db.transaction() as conn:
            if db.dialect == "mysql":
                n = conn.scalar("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()")
            else:
                n = conn.scalar("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
        return f"{n} tables present"

    def read():
        with db.transaction() as conn:
            return f"{conn.scalar('SELECT COUNT(*) FROM users')} user(s), {conn.scalar('SELECT COUNT(*) FROM projects')} project(s)"

    marker = f"dbcheck-{uuid.uuid4().hex[:8]}@example.invalid"

    def write():
        with db.transaction() as conn:
            uid = conn.insert("users", {"email": marker, "full_name": "DB check", "password_hash": "x", "created_at": utcnow()})
            assert conn.scalar("SELECT email FROM users WHERE id = ?", (uid,)) == marker
            conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        return "insert + select + delete committed"

    def rollback():
        conn = db.connect()
        try:
            conn.insert("users", {"email": marker, "full_name": "DB check", "password_hash": "x", "created_at": utcnow()})
            conn.rollback()
            left = conn.scalar("SELECT COUNT(*) FROM users WHERE email = ?", (marker,))
        finally:
            conn.close()
        assert left == 0, "row survived rollback"
        return "uncommitted insert rolled back"

    for name, fn in (("Authentication / availability", connect), ("Schema creation", schema), ("Read", read),
                     ("Write", write), ("Transaction rollback", rollback)):
        if not step(name, fn):
            print("\nDatabase check FAILED – see docs/TROUBLESHOOTING.md")
            return 1
    print("\nDatabase check PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
