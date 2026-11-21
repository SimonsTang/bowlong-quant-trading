@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Qiaoweilai-Bowlong Quant Terminal
echo ============================================================
echo  Qiaoweilai-Bowlong Quant - Web Terminal
echo ============================================================
echo.

set "PYEXE="
rem 1) WorkBuddy bundled Python (known good on this machine)
if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" set "PYEXE=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
rem 2) common CPython install locations
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
rem 3) any real python on PATH, skipping Microsoft Store stub
if not defined PYEXE (
  for /f "delims=" %%i in ('where python 2^>nul') do (
    echo %%i | find /i "WindowsApps" >nul
    if errorlevel 1 set "PYEXE=%%i"
  )
)

if not defined PYEXE (
  echo [ERROR] No usable Python found.
  echo Install Python 3.10+ from python.org, or keep the WorkBuddy bundled Python.
  echo.
  pause
  exit /b 1
)

echo Python: %PYEXE%
"%PYEXE%" -c "import sys; print(sys.version)"
if errorlevel 1 (
  echo [ERROR] Python found but cannot run.
  pause
  exit /b 1
)

netstat -ano | findstr "127.0.0.1:8765" | findstr "LISTENING" >nul
if not errorlevel 1 (
  echo [INFO] Port 8765 is already in use. Checking service health ...
  curl -s --max-time 3 http://127.0.0.1:8765/api/status >nul 2>&1
  if not errorlevel 1 (
    echo [OK] The terminal is already running and healthy.
    echo Opening http://127.0.0.1:8765 in your browser ...
    start "" http://127.0.0.1:8765
  ) else (
    echo [WARN] Port 8765 is occupied by another program, not this service.
    echo Stop that program first, or change the port in web/server.py.
  )
  echo.
  pause
  exit /b 0
)

echo.
echo Starting server ...
echo Open http://127.0.0.1:8765 in your browser
echo Press Ctrl+C in this window to stop the server.
echo.
"%PYEXE%" "%~dp0web\server.py"
set "RC=%ERRORLEVEL%"
echo.
echo Server exited with code %RC%
pause
