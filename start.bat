@echo off
REM ============================================================
REM  IdeaVault launcher for Windows
REM  Double-click this file to start the app.
REM ============================================================
cd /d "%~dp0"

echo.
echo  IdeaVault - starting up...
echo.

REM --- Check Python ---
where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python was not found. Install it from https://www.python.org/downloads/
  echo     During install, tick "Add python.exe to PATH".
  pause
  exit /b 1
)

REM --- Create a virtual environment on first run ---
if not exist ".venv\" (
  echo  Creating virtual environment ^(first run only^)...
  python -m venv .venv
)

REM --- Install dependencies ---
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

REM --- Friendly reminder about Ollama ---
where ollama >nul 2>nul
if errorlevel 1 (
  echo.
  echo  [note] Ollama was not found. The app still runs, but ideas go to
  echo         "Inbox" without auto-organizing. Install from https://ollama.com
  echo         then run:  ollama pull gemma4:e2b
  echo.
)

REM --- Open the browser, then run the server ---
start "" http://localhost:5000
echo  Opening http://localhost:5000  (press Ctrl+C here to stop)
python app.py

pause
