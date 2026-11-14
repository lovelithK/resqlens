# VS Code workspace configuration

These files belong in the `.vscode` folder. They were placed here because remote
tools are not allowed to write into `.vscode` directly (VS Code can run tasks and
debug configurations from there, so you should review them first).

Install: `setup.bat` asks before copying them, or copy them yourself:

    xcopy /y /i vscode-config\*.json .vscode\

| File | Purpose |
|---|---|
| settings.json | Python interpreter (backend\venv), pytest, Pylance, formatting, SQLTools MySQL connection (asks for password) |
| launch.json | Debug: backend (uvicorn), pytest, database check, frontend in Edge, full-stack compound |
| tasks.json | Setup, start backend/frontend/everything, tests, DB check, build, type-check |
| extensions.json | Recommended extensions |
