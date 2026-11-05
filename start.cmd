@echo off
rem Starts the Agent Team server on http://localhost:8000 and opens the dashboard.
rem Windows blocks the venv's python.exe launcher on this machine, so this uses the
rem uv-managed Python directly with the venv's packages on PYTHONPATH.
cd /d "%~dp0"

set "PY="
for /d %%D in ("%APPDATA%\uv\python\cpython-3.12*") do set "PY=%%D\python.exe"
if not exist "%PY%" (
  echo Python 3.12 from uv not found. Run:  uv python install 3.12  and  uv sync
  pause
  exit /b 1
)

set "PYTHONPATH=%~dp0.venv\Lib\site-packages;%~dp0"
start "" http://localhost:8000
echo Agent Team running on http://localhost:8000  (close this window to stop it)
"%PY%" -m uvicorn app.main:create_app --factory --port 8000
pause
