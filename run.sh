#!/usr/bin/env bash
# macOS/Linux: setup (first run) + start backend on :8000 (serves the built frontend).
set -e
cd "$(dirname "$0")"
[ -d backend/venv ] || python3 -m venv backend/venv
source backend/venv/bin/activate
pip install -q -r backend/requirements.txt
if [ ! -f .env ]; then
  cp .env.example .env
  KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
  sed -i.bak "s|^SECRET_KEY=$|SECRET_KEY=$KEY|; s|^DB_ENGINE=mysql|DB_ENGINE=sqlite|" .env && rm -f .env.bak
  echo "Created .env (SQLite). Edit it to use MySQL."
fi
cd backend
echo "ResQLens: http://localhost:8000  docs: http://localhost:8000/docs  (demo: demo@resqlens.dev / Demo@2026)"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
