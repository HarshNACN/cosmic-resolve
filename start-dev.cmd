@echo off
REM Starts the backend and all three frontends, each in its own window. Open http://localhost:5173 only: that is the
REM landing page, and it forwards /internal/ (case workbench), /support/ (customer portal) and /api. Close the windows to stop.
REM   start-dev.cmd         offline rules (no AWS needed)
REM   start-dev.cmd live    live Bedrock agent loop (run "aws login --profile bootcamp --region us-east-2" first)
REM A .cmd file is used because PowerShell script execution is blocked on some machines.
setlocal
cd /d "%~dp0"

REM MODEL_PROVIDER is set explicitly both ways, because a value in .env would otherwise decide for you.
set "BACKEND_ENV=set MODEL_PROVIDER=offline&& set CHECKPOINT_WRITES_ENABLED=true"
if /i "%~1"=="live" set "BACKEND_ENV=set AWS_PROFILE=bootcamp&& set AWS_REGION=us-east-2&& set MODEL_PROVIDER=bedrock&& set CHECKPOINT_WRITES_ENABLED=true"

start "Cosmic Resolve backend :8000" /d "%~dp0backend" cmd /k "%BACKEND_ENV%&& python -m uvicorn api:app --port 8000"
start "Internal workbench :5175" /d "%~dp0frontend" cmd /k "npm.cmd run dev"
start "Customer portal :5174" /d "%~dp0customer-frontend" cmd /k "npm.cmd run dev"
start "Landing page :5173" /d "%~dp0landing" cmd /k "npm.cmd run dev"

echo Started. Open http://localhost:5173/  (workbench: /internal/, customer portal: /support/)
endlocal
