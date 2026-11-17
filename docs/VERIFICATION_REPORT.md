# ResQLens – Local environment verification report

**Machine:** Windows 10 Pro 64-bit (build 19045), laptop "lovelith"  ·  **Date:** 14 Nov 2026
**Project folder:** `C:\Users\Lovelith\Desktop\resqlens`  ·  **Git:** branch `main`, initial commit `c38378a` (147 files)

All results below come from evidence: `logs\environment_report.txt`, `logs\verification_report.txt`, `logs\git_report.txt` and live tests run in the browser against the running app on `localhost`.

## Final status

| Requirement | Status | Verification |
|---|---|---|
| Environment | ✅ Completed | Python 3.10.11, Node 22.19.0, npm 10.9.3, Git 2.55 (user configured), PowerShell 5.1; admin-group account |
| VS Code | ✅ Completed | VS Code 1.146 with Python, Pylance and Debugger; workspace settings, debug launch configs and tasks installed from `vscode-config/` into `.vscode/` (committed). Remaining recommended extensions are offered by VS Code's prompt |
| Python | ✅ Completed | `backend\venv` created; all packages import (starlette 1.7.0, pydantic 2.14.3, PyMySQL 2.2.8, …) |
| Node.js | ✅ Completed | `npm install` done; production build passes; `tsc --noEmit` **0 errors** |
| MySQL Server | ✅ Completed | Service `MySQL80` running (server **8.0.46**), port 3306 |
| MySQL Workbench | ⚠️ Installed, connection not confirmed | Workbench 8.0 is installed. The `ResQLens Local` connection (127.0.0.1:3306, user `resqlens_app`, schema `resqlens_db`) needs to be created and tested by the user |
| Database connection | ✅ Completed | `resqlens_db` + `resqlens_test` (utf8mb4) and the least-privilege user `resqlens_app`; check passed: auth, 17 tables, read, write, rollback |
| Backend | ✅ Completed | http://localhost:8000; `/api/health` → `mysql 8.0.46`; `/docs` (Swagger UI) and `/openapi.json` served |
| Frontend | ✅ Completed | http://localhost:5173 dev server with live reload; production build served at :8000 |
| API integration | ✅ Completed | UI login and all API calls go through the 5173 → 8000 proxy (no CORS issues); no JavaScript errors in the console |
| Functional tests | ✅ Completed | 37/37 backend tests on SQLite **and** 37/37 on MySQL; 10/10 workflow tests below |
| Local execution | ✅ Completed | `start_resqlens.bat` starts everything; data and login survive a full restart |
| GitHub preparation | ✅ Completed (local) / ⏳ Push pending | Repository initialised, secret scan passed, initial commit created. Not pushed: needs a GitHub repository URL and the user's approval |
| Deployment | ⏳ Prepared, not deployed | Dockerfile, Docker Compose (app + MySQL), production env template, hosting guide (Render + Aiven / TiDB Cloud). Nothing published, per instructions |

## Functional workflow tests (run against MySQL, through http://localhost:5173)

| # | Workflow | Result | Evidence |
|---|---|---|---|
| 1 | Authentication | ✅ | register 201 · no-token access 401 · login 200 · logout → token revoked (`SESSION_REVOKED`) |
| 2 | Project management | ✅ | create, edit and delete; persisted in MySQL |
| 3 | Architecture builder | ✅ | 4 components added, edited and deleted; dependencies created; circular dependency rejected (409); reload: 4 components, 2 deps, valid |
| 4 | Failure simulation | ✅ | Question Database FAILED → Examination, Submission and Results BLOCKED; Notification, Email, Profile and Gateway unaffected |
| 5 | Impact analysis | ✅ | 1 direct, 2 indirect, 4 total; path QDB → Exam → Submission → Results; score 44.7 MODERATE at the scenario's 45 min (44.4 at 30 min, as the documented formula predicts) |
| 6 | Root cause analysis | ✅ | verified = Question Database; inferred analysis agrees; every secondary effect traced to it |
| 7 | Recovery recommendations | ✅ | 4 strategies; dependency-first order QDB → Exam → Submission → Results; invalid manual order rejected (422) |
| 8 | Recovery execution | ✅ | 4/4 actions step by step; all components HEALTHY; health 63.4 % → 100 %; simulation RECOVERED |
| 9 | Reporting | ✅ | PDF (valid `%PDF`, 11 KB), CSV (16 rows), JSON report with root cause, impact, plan and 14 timeline events |
| 10 | Persistence | ✅ | after stopping and restarting both servers: 2 users, 1 project (15 components), 1 recovered simulation — identical to the pre-restart baseline |

## Issues found and fixed during setup
| Issue | Cause | Fix |
|---|---|---|
| Verification showed `/openapi.json` FAIL | Counting bug in the check script on Windows PowerShell 5.1 (the endpoint itself worked) | `tools/verify_resqlens.ps1` corrected |
| Git secret check blocked the commit | The first secret pattern also matched documentation text such as "set `DB_PASSWORD=`" | Pattern tightened and tested (no false positives; still catches real passwords) |
| Servers didn't start after the restart and file writes failed | **C: drive full** | User freed disk space; restart then succeeded |
| Remote tools can't write `.vscode/` or `.env.*` | Safety restriction | Config shipped in `vscode-config/`; `setup.bat` asks before installing it |

## Notes and recommendations
- **Disk space:** C: had only ~5.8 GB free at the start. Keep at least 5 GB free, or move the project to E: (re-run `setup.bat` after moving).
- The `MySQL80` service runs MySQL **8.0.46**. A MySQL 8.4 folder was also present earlier; one server is enough.
- A test account (`qa…@resqlens.test`, "QA Tester") was created by the functional tests. It's harmless and can be left in place.
- Backups: `database\backup.bat`. Never expose the local MySQL to the internet; use a hosted MySQL for public deployment (`deployment/DEPLOYMENT.md`).

## Daily use
`start_resqlens.bat` → http://localhost:5173 (demo: `demo@resqlens.dev` / `Demo@2026`) · API docs http://localhost:8000/docs · re-check anytime with `verify_resqlens.bat`.
