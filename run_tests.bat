@echo off
rem ---------------------------------------------------------------------------
rem  AgentHubNext health suite - the one command.
rem
rem    run_tests.bat                 default run (config + smoke checks)
rem    run_tests.bat --live          also run real 3D / video generation (slow, billable)
rem    run_tests.bat --env DEV       test another environment for this run
rem    run_tests.bat --no-open       do not open the report in the browser
rem
rem  First run creates .venv and installs the dependencies; later runs reuse it
rem  and reinstall only when requirements.txt changes.
rem  The report is written to results\result.html, the logs of each run to
rem  logs\<start time>\ (the newest five runs are kept). Dependency installation
rem  output goes to logs\setup.log.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"
set "VENV=.venv"
set "PY=%VENV%\Scripts\python.exe"

if exist "%PY%" goto :deps
echo [setup] Creating the virtual environment in %VENV% ...
set "BASEPY="
where py >nul 2>nul && set "BASEPY=py -3"
if not defined BASEPY (where python >nul 2>nul && set "BASEPY=python")
if not defined BASEPY (
  echo [setup] Python was not found. Install Python 3.9 or newer from https://www.python.org/downloads/
  echo         and tick "Add python.exe to PATH" during installation, then run this again.
  exit /b 2
)
%BASEPY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"
if errorlevel 1 (
  echo [setup] Python 3.9 or newer is required.
  %BASEPY% --version
  exit /b 2
)
%BASEPY% -m venv "%VENV%"
if errorlevel 1 ( echo [setup] Could not create %VENV%. & exit /b 2 )

:deps
set "STAMP=%VENV%\requirements.installed"
fc /b requirements.txt "%STAMP%" >nul 2>nul
if not errorlevel 1 goto :envfile
echo [setup] Installing dependencies ...
if not exist "logs" mkdir "logs"
echo ==== %DATE% %TIME% >> "logs\setup.log"
"%PY%" -m pip install --disable-pip-version-check --quiet --upgrade pip >> "logs\setup.log" 2>&1
"%PY%" -m pip install --disable-pip-version-check --quiet -r requirements.txt >> "logs\setup.log" 2>&1
if errorlevel 1 ( echo [setup] Dependency installation failed - see logs\setup.log. & exit /b 2 )
copy /y requirements.txt "%STAMP%" >nul

:envfile
if exist ".env" goto :run
echo [setup] .env not found - generating it once from the agent-hub-backend repository ...
"%PY%" scripts\refresh_env.py
if errorlevel 1 (
  echo [setup] Could not create .env. Run scripts\refresh_env.py with the repository path as argument.
  exit /b 2
)

:run
"%PY%" -m agenthub_health %*
exit /b %errorlevel%
