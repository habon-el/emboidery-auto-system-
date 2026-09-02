@echo off
REM One-command "did the latest update work" check, for Windows.
REM
REM   scripts\verify.bat
REM
REM Pulls the latest code, makes sure the venv has whatever new
REM dependencies were added, runs the full test suite, and then starts
REM the local web UI and opens it in your browser -- so every update
REM ends with something you can actually click through, not just a
REM wall of test output. See scripts/verify.sh for the Linux/macOS
REM equivalent. Double-click this file, or run it from cmd.exe.

cd /d %~dp0..

echo == git pull ==
git pull
if errorlevel 1 goto :error

if not exist .venv (
    echo == creating .venv ^(first run^) ==
    python -m venv .venv
)
call .venv\Scripts\activate.bat

echo == installing/updating dependencies ==
pip install -q -r requirements.txt
if errorlevel 1 goto :error

echo.
echo == running the full test suite ==
python -m pytest tests/ -q
if errorlevel 1 goto :error

echo.
echo == starting the web UI at http://127.0.0.1:5000 ==
start "Embroidery Editor server" cmd /k python -m webapp.app
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:5000

echo.
echo Server is running in its own window. Close that window to stop it.
goto :eof

:error
echo.
echo Something failed above -- see the output for details.
pause
