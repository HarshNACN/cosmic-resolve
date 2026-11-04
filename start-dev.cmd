@echo off
REM Starts the backend and both frontends, each in its own window. Open http://localhost:5173 (internal)
REM and http://localhost:5173/support/ (customer). Close the windows to stop.
REM   start-dev.cmd         offline rules (no AWS needed)
REM   start-dev.cmd live    live Bedrock agent loop (run "aws login --profile bootcamp --region us-east-2" first)
REM A .cmd file is used because PowerShell script execution is blocked on some machines.
setlocal
cd /d "%~dp0"

set "BACKEND_ENV=set CHECKPOINT_WRITES_ENABLED=true"
if /i "%~1"=="live" set "BACKEND_ENV=set AWS_PROFILE=bootcamp&& set AWS_REGION=us-east-2&& set COSMIC_RESOLVE_LIVE=true&& set COSMIC_RESOLVE_PIPELINE=agent&& set CHECKPOINT_WRITES_ENABLED=true"

start "Cosmic Resolve backend :8000" /d "%~dp0backend" cmd /k "%BACKEND_ENV%&& python -m uvicorn api:app --port 8000"
start "Customer portal :5174" /d "%~dp0customer-frontend" cmd /k "npm.cmd run dev"
start "Internal workbench :5173" /d "%~dp0frontend" cmd /k "npm.cmd run dev"

echo Started. Internal: http://localhost:5173/   Customer: http://localhost:5173/support/
endlocal
