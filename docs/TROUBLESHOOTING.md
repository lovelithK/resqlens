# Troubleshooting

Start with the exact error text in the backend window, the frontend window, or the browser console (`F12`).

## Python and setup
| Symptom | Cause → fix |
|---|---|
| `'python' is not recognized` | Python is not on PATH. Re-run the Python installer → *Modify* → tick *Add to environment variables*, or use `py -3` in place of `python`. If typing `python` opens the Microsoft Store: *Settings → Apps → Advanced app settings → App execution aliases* → turn off the `python.exe` aliases. |
| PowerShell: `running scripts is disabled` when activating the venv | Use Command Prompt (`venv\Scripts\activate.bat`), or allow it only for this window: `Set-ExecutionPolicy -Scope Process Bypass`. The `.bat` scripts don't need this. |
| `pip install` fails building `cryptography` / `pandas` | Very new or very old Python. Use Python 3.12 or 3.13 (prebuilt wheels exist). Upgrade pip: `python -m pip install --upgrade pip`. |
| `ModuleNotFoundError: app` | Run backend commands from inside `backend\`, or use the scripts or VS Code tasks. |

## MySQL
| Symptom | Cause → fix |
|---|---|
| `Can't connect to MySQL server on '127.0.0.1' (10061)` | The MySQL service is stopped. `services.msc` → MySQL80/MySQL84 → Start, or in an admin terminal: `net start MySQL80`. Check the port: `netstat -ano \| findstr :3306`. |
| `Access denied for user 'resqlens_app'@'localhost'` | `DB_PASSWORD` in `.env` doesn't match the password in `create_database.sql`. Reset it as root: `ALTER USER 'resqlens_app'@'localhost' IDENTIFIED BY '...'; ALTER USER 'resqlens_app'@'127.0.0.1' IDENTIFIED BY '...';` |
| `Unknown database 'resqlens_db'` | `create_database.sql` wasn't run (step 2 of SETUP_WINDOWS). |
| `cryptography package is required for sha256_password or caching_sha2_password` | `pip install -r backend\requirements.txt` (it includes `cryptography`). |
| `CREATE command denied` | The app user is missing the grants; re-run the GRANT lines of `create_database.sql`. |
| `mysql` command not found | Workbench is enough, or call `"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe"`. |
| I want to start without MySQL | Set `DB_ENGINE=sqlite` in `.env` (a file `backend\resqlens.db` is used). |

## Servers and ports
| Symptom | Cause → fix |
|---|---|
| `[Errno 10048] ... only one usage of each socket address` (port 8000) or `Port 5173 is already in use` | Another instance is running. Find it with `netstat -ano \| findstr :8000`, then `taskkill /PID <pid> /F`. Or use another port: `npm run dev -- --port 5174`. |
| UI shows *Cannot reach the ResQLens server* or *Backend not reachable* | The backend isn't running or crashed; read the backend window. |
| Browser shows a CORS error | Only happens if you serve the UI from an origin not in `CORS_ORIGINS`. Add it to `.env` and restart the backend. The 5173 dev server proxies `/api`, so it never needs CORS. |
| Logged out after restarting the backend | `SECRET_KEY` is empty in `.env` (a random one is generated each start). Set a fixed one. |
| `/docs` page is blank | Swagger UI loads from a CDN (`cdn.jsdelivr.net`), so internet access is needed. The raw spec is always available at `/openapi.json`. |

## Frontend
| Symptom | Cause → fix |
|---|---|
| `npm` not found | Install Node.js LTS and reopen VS Code so PATH refreshes. |
| `npm run typecheck` errors about `react` types | Run `npm install` in `frontend` (installs `@types/react`). |
| UI changes don't appear on :8000 | :8000 serves the production build. Run `npm run build`, or use :5173 for live reload. |

## Still stuck?
Run the database check (`python -m scripts.check_db`), the tests (`python -m pytest -q`), and `curl http://localhost:8000/api/health`. Their output pinpoints which layer is failing.
