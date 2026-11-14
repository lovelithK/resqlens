"""One-time MySQL setup for ResQLens (run via database\\setup_mysql.bat).

* asks for the MySQL root password (hidden, used once, never stored)
* asks you to choose a password for the application user `resqlens_app` (hidden)
* creates resqlens_db + resqlens_test (utf8mb4) and the least-privilege user
* writes DB_ENGINE=mysql and DB_PASSWORD=<app password> into the project's .env
  (git-ignored), leaving every other line unchanged
* finally runs the database check (schema creation, read, write, rollback)
"""
from __future__ import annotations

import getpass
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / ".env"


def read_env() -> dict:
    vals = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    return vals


def write_env(updates: dict) -> None:
    lines = ENV.read_text(encoding="utf-8-sig").splitlines() if ENV.exists() else []
    done = set()
    for i, line in enumerate(lines):
        m = re.match(r"^\s*([A-Z_]+)\s*=", line)
        if m and m.group(1) in updates:
            lines[i] = f"{m.group(1)}={updates[m.group(1)]}"
            done.add(m.group(1))
    for k, v in updates.items():
        if k not in done:
            lines.append(f"{k}={v}")
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    try:
        import pymysql
    except ImportError:
        print("[ERROR] PyMySQL missing - run setup.bat first.")
        return 1
    if not ENV.exists():
        print("[ERROR] .env missing - run setup.bat first.")
        return 1
    env = read_env()
    host, port = env.get("DB_HOST") or "127.0.0.1", int(env.get("DB_PORT") or 3306)
    db_name, app_user = env.get("DB_NAME") or "resqlens_db", env.get("DB_USER") or "resqlens_app"

    print(f"\nResQLens MySQL setup  ->  {host}:{port}, database '{db_name}', app user '{app_user}'\n")
    admin = input("MySQL admin user [root]: ").strip() or "root"
    admin_pw = getpass.getpass(f"Password for MySQL user '{admin}' (hidden): ")
    try:
        conn = pymysql.connect(host=host, port=port, user=admin, password=admin_pw, charset="utf8mb4", autocommit=True)
    except Exception as exc:
        print(f"\n[ERROR] Could not log in as '{admin}': {exc}")
        print("        Check the password (it is the one chosen when MySQL was installed) and that the MySQL80 service is running.")
        return 1
    admin_pw = None

    while True:
        pw1 = getpass.getpass(f"Choose a password for the app user '{app_user}' (min 8 chars, hidden): ")
        if len(pw1) < 8 or not re.search(r"\d", pw1) or not re.search(r"[A-Za-z]", pw1):
            print("  Use at least 8 characters with letters and a digit.")
            continue
        if any(c in pw1 for c in "'\"\\ #"):
            print("  Please avoid quotes, backslashes, spaces and '#' (they break .env parsing).")
            continue
        if getpass.getpass("Repeat the app password: ") != pw1:
            print("  Passwords do not match, try again.")
            continue
        break

    statements = [
        f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci",
        "CREATE DATABASE IF NOT EXISTS `resqlens_test` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci",
    ]
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)
        for h in ("localhost", "127.0.0.1"):
            cur.execute("CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s", (app_user, h, pw1))
            cur.execute("ALTER USER %s@%s IDENTIFIED BY %s", (app_user, h, pw1))
            cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES ON `{db_name}`.* TO %s@%s",
                        (app_user, h))
            cur.execute("GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES, DROP "
                        "ON `resqlens_test`.* TO %s@%s", (app_user, h))
        cur.execute("FLUSH PRIVILEGES")
        cur.execute("SHOW GRANTS FOR %s@'localhost'", (app_user,))
        grants = [r[0] for r in cur.fetchall()]
    conn.close()
    print("\n[OK] Databases ready: " + db_name + ", resqlens_test")
    print(f"[OK] User '{app_user}' ready with grants:")
    for g in grants:
        print("     " + g.replace(pw1, "***"))

    write_env({"DB_ENGINE": "mysql", "DB_PASSWORD": pw1})
    print("[OK] .env updated: DB_ENGINE=mysql, DB_PASSWORD set (value not shown; .env is git-ignored)\n")

    print("Running the database check with the app user...")
    import os
    os.environ["DB_ENGINE"] = "mysql"
    os.environ["DB_PASSWORD"] = pw1
    from scripts.check_db import main as check
    return check()


if __name__ == "__main__":
    sys.exit(main())
