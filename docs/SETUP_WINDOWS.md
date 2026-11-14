# ResQLens: Windows setup with VS Code and MySQL

This guide takes a fresh clone or unzip to a running app at **http://localhost:5173**, with the API on **http://localhost:8000** and API docs at **http://localhost:8000/docs**.

## 0. Prerequisites (install only what is missing)
Check in **Command Prompt** or **PowerShell**:
```bat
python --version      & REM 3.10 or newer
node --version        & REM 18 or newer (LTS recommended)
npm --version
git --version
mysql --version       & REM optional; Workbench can do everything instead
```

| Software | Download | Note |
|---|---|---|
| Python 3.12/3.13 | https://www.python.org/downloads/windows/ | tick **"Add python.exe to PATH"** |
| Node.js LTS | https://nodejs.org/ | includes npm |
| Git | https://git-scm.com/download/win | |
| VS Code | https://code.visualstudio.com/ | |
| MySQL Server 8 + Workbench | https://dev.mysql.com/downloads/installer/ | choose *Server* + *Workbench*, port 3306, run as a Windows service |

If `mysql` is not recognised but MySQL is installed, it is simply not on PATH. Workbench is enough, or use `"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe"`.

## 1. Open the project in VS Code
`File → Open Folder…` → the `resqlens` folder. The workspace settings, debug configurations, tasks and extension recommendations ship in `vscode-config\`. `setup.bat` (step 3) asks before copying them into `.vscode\`. Afterwards, accept **"Install recommended extensions"**: Python, Pylance, Python Debugger, ESLint, Prettier, SQLTools + MySQL driver, GitLens, REST Client, ES7 React snippets.

## 2. Create the database (once)
**Easiest:** after step 3, double-click `database\setup_mysql.bat`. It asks for the MySQL root password and a new app password (both hidden), creates the databases and the user, writes the app password into `.env`, and runs the connection check.

**Or with MySQL Workbench:**
1. Workbench → **+** next to *MySQL Connections*. Name `ResQLens Local (root)`, Hostname `127.0.0.1`, Port `3306`, Username `root` → **Test Connection** (enter the root password in Workbench, never in chat or code).
2. Open that connection → *File → Open SQL Script…* → `database\create_database.sql`.
3. Replace both `CHANGE_ME_Strong_Password_1` placeholders with a password of your choice for the **application user** `resqlens_app`.
4. Click ⚡ **Execute**. The output ends with the user's grants.
5. Optional: add a second Workbench connection `ResQLens Local` with user `resqlens_app` and default schema `resqlens_db`, for browsing the app's tables.

Command-line alternative (prompts for the root password):
```bat
mysql -u root -p < database\create_database.sql
```

## 3. Install everything
In the VS Code terminal (`` Ctrl+` ``), from the project folder:
```bat
setup.bat
```
It creates `backend\venv`, installs the Python packages, creates `.env` with a random `SECRET_KEY`, runs `npm install`, and builds the frontend.

Open **`.env`** and set `DB_PASSWORD=` to the application user's password from step 2. Check that `DB_ENGINE=mysql`.

## 4. Verify the database connection
```bat
backend\venv\Scripts\activate
cd backend
python -m scripts.check_db
```
It checks authentication, availability, schema creation (17 tables), read, write and transaction rollback, and should end with `Database check PASSED`.

## 5. Run
```bat
start_resqlens.bat
```
The script:
1. checks the setup and the MySQL Windows service,
2. starts the backend window and waits for `/api/health`,
3. starts the frontend window,
4. opens http://localhost:5173.

Sign in with `demo@resqlens.dev` / `Demo@2026`, or register.

Alternatives:
- `start_backend.bat` and `start_frontend.bat` start each side separately.
- In VS Code: *Terminal → Run Task → ResQLens: start everything*, or *Run and Debug → "ResQLens: full stack"* (breakpoints in Python and TypeScript).

| URL | What |
|---|---|
| http://localhost:5173 | frontend dev server (live reload; `/api` proxied to :8000) |
| http://localhost:8000 | backend, also serving the latest production build of the UI |
| http://localhost:8000/docs | interactive API docs (Swagger UI; click **Authorize** and paste a login token) |
| http://localhost:8000/api/health | health and database check |

## 6. Tests
```bat
cd backend
venv\Scripts\activate
python -m pytest -q                                  & REM SQLite (fast, isolated)
set TEST_DB_ENGINE=mysql& python -m pytest -q        & REM same tests on MySQL database resqlens_test
```

## 7. Daily use
- Start: `start_resqlens.bat`. Stop: close the two server windows, or press `Ctrl+C` in them.
- Make sure the MySQL service is running: `services.msc` → **MySQL80/MySQL84** → *Startup type: Automatic*.
- Backup: `database\backup.bat` writes to `database\backups\` (git-ignored).
- Frontend production build after UI changes: `cd frontend && npm run build`.

Problems? See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
